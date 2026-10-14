from pathlib import Path
import hashlib
import pickle
import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch_geometric.utils import to_undirected
from src.utils.io import ROOT, load_config, save_json, read_json
from src.utils.logging import get_logger


def split_nodes(labels, timesteps, ratios, seed):
    known = np.flatnonzero(labels >= 0)
    masks = [np.zeros(len(labels), dtype=bool) for _ in range(3)]
    metadata = {}
    if timesteps is not None:
        steps = np.sort(np.unique(timesteps[known]))
        if len(steps) < 3:
            raise ValueError("Time split needs at least three labeled timesteps.")
        n_train = min(max(1, int(len(steps) * ratios[0])), len(steps) - 2)
        n_val = min(max(1, int(len(steps) * ratios[1])), len(steps) - n_train - 1)
        cuts = (steps[n_train - 1], steps[n_train + n_val - 1])
        masks[0][known] = timesteps[known] <= cuts[0]
        masks[1][known] = (timesteps[known] > cuts[0]) & (timesteps[known] <= cuts[1])
        masks[2][known] = timesteps[known] > cuts[1]
        metadata = {"method": "time", "train_end": float(cuts[0]), "val_end": float(cuts[1]),
                    "timesteps": steps.tolist()}
    else:
        train, rest = train_test_split(known, test_size=1-ratios[0], stratify=labels[known], random_state=seed)
        val, test = train_test_split(rest, test_size=ratios[2]/sum(ratios[1:]),
                                    stratify=labels[rest], random_state=seed)
        for mask, ids in zip(masks, (train, val, test)):
            mask[ids] = True
        metadata = {"method": "stratified", "seed": seed}
    for name, mask in zip(("train", "val", "test"), masks):
        if not mask.any() or len(np.unique(labels[mask])) < 2:
            raise ValueError(f"{name} split has fewer than two classes; check timestep/label mapping or sample size.")
        metadata[name] = {"nodes": int(mask.sum()), "illicit": int((labels[mask] == 1).sum())}
    return masks, metadata


def preprocess(root: Path = ROOT, max_nodes=None):
    cfg = load_config("data.yaml", root)
    c, d, p = cfg["columns"], cfg["dataset"], cfg["preprocessing"]
    logger = get_logger("preprocess", root)
    out = root / "data/processed"
    out.mkdir(parents=True, exist_ok=True)
    ids, label_col, time_col = c["address_id"], c["label"], c.get("timestep")
    label_table = pd.read_csv(root / d["labels_file"], dtype=str)
    for column in (ids, label_col):
        if column not in label_table:
            raise ValueError(f"Missing label column: {column}. Adapt config/data.yaml.")
    if label_table.groupby(ids)[label_col].nunique().max() > 1:
        raise ValueError("Conflicting labels for duplicate addresses.")
    label_table = label_table.drop_duplicates(ids)
    mapping = {str(k).lower(): int(v) for k, v in cfg["label_map"].items()}
    mapped = label_table[label_col].str.strip().str.lower().map(mapping)
    if mapped.isna().any():
        raise ValueError(f"Unmapped labels: {label_table.loc[mapped.isna(), label_col].unique().tolist()}")
    label_lookup = dict(zip(label_table[ids], mapped.astype(int)))
    max_nodes = max_nodes if max_nodes is not None else p.get("max_nodes")
    selected = None
    if max_nodes is not None and max_nodes < len(label_table):
        picked, _ = train_test_split(label_table[ids].to_numpy(), train_size=int(max_nodes),
                                     stratify=mapped.to_numpy(), random_state=p["seed"])
        selected = set(picked)
    header = pd.read_csv(root / d["features_file"], nrows=0).columns.tolist()
    if ids not in header:
        raise ValueError(f"Feature ID column {ids!r} absent. Adapt config/data.yaml.")
    excluded = {ids, label_col, time_col, *p.get("exclude_columns", [])}
    feature_names = [name for name in header if name not in excluded and not name.startswith("Unnamed:")]
    dtype = {name: "float32" for name in feature_names}
    dtype[ids] = str
    parts, raw_rows, selected_raw_rows = [], 0, 0
    for chunk in pd.read_csv(root / d["features_file"], dtype=dtype, chunksize=p["feature_chunksize"]):
        raw_rows += len(chunk)
        if chunk[ids].isna().any():
            raise ValueError("Feature table contains missing address IDs.")
        if selected is not None:
            chunk = chunk[chunk[ids].isin(selected)]
        selected_raw_rows += len(chunk)
        if time_col in chunk and p["duplicate_policy"] == "latest_timestep":
            chunk = chunk.sort_values(time_col, kind="stable")
        parts.append(chunk.drop_duplicates(ids, keep="last"))
    frame = pd.concat(parts, ignore_index=True)
    before_dedup = len(frame)
    if time_col in frame and p["duplicate_policy"] == "latest_timestep":
        frame = frame.sort_values(time_col, kind="stable")
    elif frame[ids].duplicated().any() and p["duplicate_policy"] == "error":
        raise ValueError("Duplicate addresses found.")
    frame = frame.drop_duplicates(ids, keep="last").sort_values(ids).reset_index(drop=True)
    addresses = frame[ids].astype(str).tolist()
    address_to_idx = {address: idx for idx, address in enumerate(addresses)}
    labels = np.array([label_lookup.get(address, -1) for address in addresses], dtype=np.int64)
    times = frame[time_col].to_numpy(dtype=np.float64) if time_col in frame else None
    if times is not None and not np.isfinite(times).all():
        raise ValueError("Timestep contains non-finite values.")
    masks, split_metadata = split_nodes(labels, times, p["split_ratios"], p["seed"])
    raw_features = frame[feature_names].to_numpy(dtype=np.float32)
    raw_features[~np.isfinite(raw_features)] = np.nan
    # Fitting only on train avoids leakage. Entirely missing training fields get a zero baseline.
    train_frame = pd.DataFrame(raw_features[masks[0]])
    medians = train_frame.median().fillna(0).to_numpy(dtype=np.float32)
    imputed = np.where(np.isnan(raw_features), medians, raw_features)
    scaler = StandardScaler().fit(imputed[masks[0]])
    features = scaler.transform(imputed).astype(np.float32)
    if not np.isfinite(features).all():
        raise ValueError("Non-finite standardized features.")
    edges, total_edges, dropped_edges = [], 0, 0
    for chunk in pd.read_csv(root / d["edges_file"], dtype=str, chunksize=p["edge_chunksize"]):
        if c["src"] not in chunk or c["dst"] not in chunk:
            raise ValueError("Missing edge columns. Adapt config/data.yaml.")
        total_edges += len(chunk)
        src, dst = chunk[c["src"]].map(address_to_idx), chunk[c["dst"]].map(address_to_idx)
        valid = src.notna() & dst.notna()
        dropped_edges += int((~valid).sum())
        edges.append(np.stack((src[valid].to_numpy(dtype=np.int64), dst[valid].to_numpy(dtype=np.int64))))
    edge_array = np.concatenate(edges, axis=1)
    edge_array = np.unique(edge_array, axis=1)
    if not edge_array.shape[1]:
        raise ValueError("No edges survived ID mapping; verify column names or increase pilot sample.")
    directed = torch.from_numpy(edge_array)
    model_edges = to_undirected(directed, num_nodes=len(addresses))
    outgoing, incoming = {}, {}
    for src, dst in edge_array.T:
        outgoing.setdefault(int(src), []).append(int(dst))
        incoming.setdefault(int(dst), []).append(int(src))
    for name, array in (("features", features), ("raw_features", raw_features), ("labels", labels),
                        *zip(("train_mask", "val_mask", "test_mask"), masks)):
        np.save(out / f"{name}.npy", array)
    if times is not None:
        np.save(out / "timesteps.npy", times)
    else:
        (out / "timesteps.npy").unlink(missing_ok=True)
    torch.save(model_edges, out / "edge_index.pt")
    torch.save(directed, out / "edge_index_directed.pt")
    for name, neighbors in (("outgoing_neighbors", outgoing), ("incoming_neighbors", incoming)):
        with (out / f"{name}.pkl").open("wb") as stream:
            pickle.dump(neighbors, stream)
    joblib.dump(scaler, out / "scaler.pkl")
    joblib.dump(medians, out / "imputer.pkl")
    save_json(out / "address_to_idx.json", address_to_idx)
    save_json(out / "idx_to_address.json", {str(i): a for i, a in enumerate(addresses)})
    save_json(out / "feature_names.json", feature_names)
    content_hash = hashlib.sha256(("\n".join(addresses) + json_fingerprint(cfg)).encode())
    for array in (features, labels, edge_array, *masks):
        content_hash.update(memoryview(np.ascontiguousarray(array)))
    fingerprint = content_hash.hexdigest()
    metadata = {"dataset": d["name"], "num_nodes": len(addresses), "num_edges": edge_array.shape[1],
                "num_model_edges": model_edges.shape[1], "num_features": len(feature_names),
                "licit_count": int((labels == 0).sum()), "illicit_count": int((labels == 1).sum()),
                "unknown_count": int((labels == -1).sum()), "raw_feature_rows": raw_rows,
                "duplicate_policy": p["duplicate_policy"], "duplicate_rows_removed": selected_raw_rows-len(addresses),
                "raw_edges": total_edges, "dropped_unmapped_edges": dropped_edges,
                "scope": "full" if selected is None else "real_data_pilot",
                "requested_max_nodes": max_nodes, "split": split_metadata, "fingerprint": fingerprint,
                "limitations": ["Address snapshots may aggregate lifetime activity; timestep splitting is not an as-of-time forecasting benchmark.",
                                "The pilot, when enabled, is an induced subgraph and can omit external relations."]}
    save_json(out / "metadata.json", metadata)
    logger.info("Completed: %s", metadata)
    return metadata


def json_fingerprint(config):
    import json
    return json.dumps(config, sort_keys=True)


def load_processed(root: Path = ROOT):
    from torch_geometric.data import Data
    folder = root / "data/processed"
    x = torch.from_numpy(np.load(folder / "features.npy"))
    data = Data(x=x, y=torch.from_numpy(np.load(folder / "labels.npy")),
                edge_index=torch.load(folder / "edge_index.pt", weights_only=True))
    for name in ("train_mask", "val_mask", "test_mask"):
        setattr(data, name, torch.from_numpy(np.load(folder / f"{name}.npy")))
    if (folder / "timesteps.npy").exists():
        data.timestep = torch.from_numpy(np.load(folder / "timesteps.npy"))
    return data, read_json(folder / "metadata.json")
