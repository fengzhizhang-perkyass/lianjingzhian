from pathlib import Path
import pandas as pd
from src.utils.io import ROOT, read_json, file_sha256


class RiskPredictor:
    """Online lookup only: never retrain or run full-graph inference from a UI page."""
    def __init__(self, root: Path = ROOT):
        folder = root / "artifacts/risk_scores"
        self.table = pd.read_parquet(folder / "risk_scores.parquet")
        self.metadata = read_json(folder / "metadata.json")
        processed = read_json(root / "data/processed/metadata.json")
        if self.metadata["dataset_fingerprint"] != processed["fingerprint"]:
            raise RuntimeError("Risk table does not match the processed graph. Recompute scores.")
        for field, filename in (("model_sha256", "dual_view_model.pt"), ("calibration_sha256", "temperature.json")):
            if field in self.metadata and self.metadata[field] != file_sha256(root / "artifacts/model" / filename):
                raise RuntimeError("Risk scores belong to a different model/calibration. Recompute scores.")
        for relative, expected in self.metadata.get('source_hashes', {}).items():
            if file_sha256(root / relative) != expected:
                raise RuntimeError('Evidence scoring artifacts changed. Run script 21 again.')
        if self.metadata.get('model_kind') == 'evidence_tree':
            expected = self.metadata['source_hashes']['artifacts/evidence_scoring/risk_scores.parquet']
            if file_sha256(folder / 'risk_scores.parquet') != expected:
                raise RuntimeError('Active risk table differs from the frozen evidence scores.')
        self.by_address = self.table.set_index("address_id")
        self.by_index = self.table.set_index("node_idx")

    def resolve(self, value: str):
        value = str(value).strip()
        if value in self.by_address.index:
            return value
        if value.isdigit() and int(value) in self.by_index.index:
            return str(self.by_index.loc[int(value), "address_id"])
        raise KeyError(f"Address / node ID not found: {value}")

    def lookup(self, value: str):
        address = self.resolve(value)
        row = self.by_address.loc[address]
        return {"address_id": address, "node_idx": int(row["node_idx"]),
                "risk": {"overall_score": float(row["overall_risk_score"]), "risk_level": row["risk_level"],
                         "behavior_score": float(row["behavior_score"]), "graph_score": float(row["graph_score"]),
                         "behavior_weight": float(row["behavior_weight"]) if pd.notna(row["behavior_weight"]) else None,
                         "graph_weight": float(row["graph_weight"]) if pd.notna(row["graph_weight"]) else None}}
