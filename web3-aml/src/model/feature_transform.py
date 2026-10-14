"""Serializable, training-only preprocessing shared by experiments and inference."""
import numpy as np
import pandas as pd


def fit_feature_transform(raw, train_mask, feature_names, settings):
    raw = np.asarray(raw)
    train_mask = np.asarray(train_mask, dtype=bool)
    if raw.ndim != 2 or len(train_mask) != len(raw) or not train_mask.any():
        raise ValueError("Feature transform requires a nonempty training mask.")
    if raw.shape[1] != len(feature_names):
        raise ValueError("Feature names do not match input dimensions.")
    method = settings.get("method", "standard")
    if method not in {"standard", "signed_log"}:
        raise ValueError("Feature method must be standard or signed_log.")
    train = np.asarray(raw[train_mask], dtype=np.float64)
    train[~np.isfinite(train)] = np.nan
    medians = pd.DataFrame(train).median().fillna(0).to_numpy()
    train = np.where(np.isfinite(train), train, medians)
    if method == "signed_log":
        train = np.sign(train) * np.log1p(np.abs(train))
    means = train.mean(axis=0)
    scales = train.std(axis=0)
    scales[scales < np.finfo(np.float64).eps] = 1
    excluded = settings.get("exclude_features", [])
    absent = set(excluded) - set(feature_names)
    if absent:
        raise ValueError(f"Unknown excluded features: {sorted(absent)}")
    clip = settings.get("standardized_clip")
    if clip is not None and clip <= 0:
        raise ValueError("standardized_clip must be positive.")
    return {"version": 1, "method": method, "feature_names": list(feature_names),
            "medians": medians.tolist(), "means": means.tolist(), "scales": scales.tolist(),
            "standardized_clip": clip, "excluded_indices": [feature_names.index(name) for name in excluded],
            "fit_nodes": int(train_mask.sum()), "transform_chunk_rows": 8192}


def transform_features(raw, state):
    raw = np.asarray(raw)
    if raw.ndim != 2 or raw.shape[1] != len(state["means"]):
        raise ValueError("Input does not match saved feature transform.")
    result = np.empty(raw.shape, dtype=np.float32)
    chunk_rows = state.get("transform_chunk_rows", 8192)
    for start in range(0, len(raw), chunk_rows):
        values = np.array(raw[start:start+chunk_rows], dtype=np.float64, copy=True)
        values = np.where(np.isfinite(values), values, np.asarray(state["medians"]))
        if state["method"] == "signed_log":
            values = np.sign(values) * np.log1p(np.abs(values))
        values = (values - np.asarray(state["means"])) / np.asarray(state["scales"])
        if state["standardized_clip"] is not None:
            values = np.clip(values, -state["standardized_clip"], state["standardized_clip"])
        values[:, state["excluded_indices"]] = 0
        if not np.isfinite(values).all():
            raise ValueError("Non-finite model input after feature transformation.")
        result[start:start+chunk_rows] = values
    return result
