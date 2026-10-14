"""A separate review priority, expert disagreement and inquiry queues."""
import numpy as np
import pandas as pd


def blend_probabilities(probabilities, weights):
    values = np.asarray(probabilities, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != len(weights):
        raise ValueError("Expert/weight dimensions do not match.")
    if (not np.isfinite(values).all() or not np.isfinite(weights).all()
            or (values < 0).any() or (values > 1).any()
            or (weights < 0).any() or not np.isclose(weights.sum(), 1)):
        raise ValueError("Invalid probability or convex weights.")
    return values @ weights


def simplex_weights(count, step):
    units = int(round(1/step))
    if not np.isclose(units*step, 1):
        raise ValueError("Weight step must divide one.")
    import itertools
    return [np.array(values)/units for values in itertools.product(range(units+1), repeat=count)
            if sum(values) == units]


def diagnose_experts(scores, warning_thresholds=None, low_fraction=0.5):
    """Scores must be independently calibrated; disagreement is not error probability."""
    values = np.asarray(scores, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 2 or not np.isfinite(values).all():
        raise ValueError("At least two finite expert scores required.")
    thresholds = np.asarray(warning_thresholds if warning_thresholds is not None else [60]*values.shape[1])
    if ((values < 0).any() or (values > 100).any() or not 0 < low_fraction < 1
            or thresholds.shape != (values.shape[1],) or not np.isfinite(thresholds).all()
            or (thresholds <= 0).any() or (thresholds > 100).any()):
        raise ValueError("Invalid risk scores or boundaries.")
    minimum, maximum = values.min(axis=1), values.max(axis=1)
    warnings = (values >= thresholds).sum(axis=1)
    conflict = (warnings > 0) & (warnings < values.shape[1])
    status = np.full(len(values), "待复核", dtype=object)
    status[warnings == values.shape[1]] = "共识告警"
    status[(values < thresholds*low_fraction).all(axis=1)] = "一致未告警"
    status[conflict] = "模型分歧"
    return {"expert_disagreement": maximum-minimum, "expert_min": minimum,
            "expert_max": maximum, "review_status": status,
            "warning_expert_count": warnings}


class InvestigationIndex:
    def __init__(self, root, risk_revision):
        from src.utils.io import read_json, file_sha256
        folder = root / "artifacts/investigation"
        self.metadata = read_json(folder / "metadata.json")
        if self.metadata["risk_revision"] != risk_revision:
            raise RuntimeError("Investigation overlay is stale. Run script 14 again.")
        source = root / "artifacts/experiments" / self.metadata["experiment"]
        for relative, expected in self.metadata["source_hashes"].items():
            if file_sha256(root / relative) != expected:
                raise RuntimeError("Investigation expert changed. Recompute the overlay.")
        if file_sha256(source / "selection.json") != self.metadata["selection_sha256"]:
            raise RuntimeError("Investigation selection changed. Recompute the overlay.")
        if file_sha256(folder / "topology_features.npy") != self.metadata["topology_sha256"]:
            raise RuntimeError("Topology explanation cache changed. Recompute the overlay.")
        self.table = pd.read_parquet(folder / "priorities.parquet")
        self.by_address = self.table.set_index("address_id")

    def lookup(self, address):
        return self.by_address.loc[address].to_dict()
