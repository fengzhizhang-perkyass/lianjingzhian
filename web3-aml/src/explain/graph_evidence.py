from pathlib import Path
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from src.utils.io import ROOT, read_json, save_json


class GraphEvidence:
    def __init__(self, graph, risk_scores, sample_size=200, seed=42, high_risk_threshold=60):
        self.graph, self.risks = graph, risk_scores
        self.sample_size, self.seed, self.threshold = sample_size, seed, high_risk_threshold

    def explain(self, address):
        neighbors = self.graph.neighbors(address)
        risks = [self.risks[n] for n in neighbors]
        # Bound both expansion levels around hubs, before allocating a large two-hop set.
        rng = np.random.default_rng(self.seed)
        first_sample = neighbors
        if len(first_sample) > self.sample_size:
            first_sample = [first_sample[i] for i in sorted(rng.choice(len(first_sample), self.sample_size, replace=False))]
        candidates = set()
        for first in first_sample:
            second = self.graph.neighbors(first)
            if len(second) > self.sample_size:
                second = [second[i] for i in sorted(rng.choice(len(second), self.sample_size, replace=False))]
            candidates.update(second)
        two = sorted(candidates - set(neighbors) - {address})
        if len(two) > self.sample_size:
            two = [two[i] for i in sorted(rng.choice(len(two), self.sample_size, replace=False))]
        second_risks = [self.risks[n] for n in two]
        out_degree, in_degree = self.graph.degrees(address)
        return {"out_degree": out_degree, "in_degree": in_degree,
                "one_hop_neighbor_count": len(neighbors), "one_hop_avg_risk": float(np.mean(risks)) if risks else 0,
                "one_hop_high_risk_count": sum(r >= self.threshold for r in risks),
                "one_hop_high_risk_ratio": float(np.mean(np.array(risks) >= self.threshold)) if risks else 0,
                "two_hop_avg_risk": float(np.mean(second_risks)) if second_risks else 0,
                "two_hop_high_risk_ratio": float(np.mean(np.array(second_risks) >= self.threshold)) if second_risks else 0,
                "two_hop_sample_count": len(two), "neighbor_view": "unique incoming/outgoing union; self excluded",
                "high_risk_threshold": self.threshold, "two_hop_sampling": "bounded two-stage neighbor sampling"}


def precompute_graph_statistics(graph, risk_table, root: Path = ROOT, threshold=60):
    """Sparse matrix aggregation avoids Python neighbor loops over the complete graph."""
    size = len(graph.address_to_idx)
    ordered = risk_table.set_index("node_idx").reindex(range(size))
    risk = ordered["overall_risk_score"].to_numpy()
    rows, cols = [], []
    for src, neighbors in graph.outgoing.items():
        for dst in neighbors:
            if src != dst:
                rows.extend((src, dst))
                cols.extend((dst, src))
    matrix = csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(size, size))
    matrix.data[:] = 1
    counts = np.asarray(matrix.sum(axis=1)).ravel()
    average = np.asarray(matrix @ risk).ravel()/np.maximum(counts, 1)
    high = np.asarray(matrix @ (risk >= threshold).astype(float)).ravel()
    result = pd.DataFrame({"address_id": [graph.idx_to_address[i] for i in range(size)],
                           "out_degree": [len(graph.outgoing.get(i, [])) for i in range(size)],
                           "in_degree": [len(graph.incoming.get(i, [])) for i in range(size)],
                           "one_hop_neighbor_count": counts.astype(int), "one_hop_avg_risk": average,
                           "one_hop_high_risk_count": high.astype(int),
                           "one_hop_high_risk_ratio": high/np.maximum(counts, 1)})
    folder = root / "artifacts/risk_scores"
    result.to_parquet(folder / "graph_statistics.parquet", index=False)
    save_json(folder / "graph_statistics_metadata.json", {"high_risk_threshold": threshold,
               "risk_revision": read_json(folder / "metadata.json").get("risk_revision", "legacy") if (folder / "metadata.json").exists() else "legacy",
               "dataset_fingerprint": read_json(root / "data/processed/metadata.json")["fingerprint"]})
    return result
