import pandas as pd
import pytest
from src.tracing.graph_loader import DirectedGraph
from src.explain.graph_evidence import GraphEvidence, precompute_graph_statistics
from src.utils.io import artifact_key, save_json


def test_neighbors_are_unique_directed_self_excluded_and_risk_based(tmp_path):
    graph = DirectedGraph({0: [0, 1], 1: [2]}, {0: [0, 1], 1: [0], 2: [1]},
                          {"A": 0, "B": 1, "C": 2}, {"0": "A", "1": "B", "2": "C"})
    evidence = GraphEvidence(graph, {"A": 90, "B": 80, "C": 10}).explain("A")
    assert evidence["one_hop_neighbor_count"] == 1
    assert evidence["one_hop_avg_risk"] == 80
    assert evidence["one_hop_high_risk_ratio"] == 1
    assert evidence["two_hop_sample_count"] == 1 and evidence["two_hop_avg_risk"] == 10
    (tmp_path / "artifacts/risk_scores").mkdir(parents=True)
    save_json(tmp_path / "data/processed/metadata.json", {"fingerprint": "test"})
    stats = precompute_graph_statistics(graph, pd.DataFrame({"node_idx": [0, 1, 2], "overall_risk_score": [90, 80, 10]}), tmp_path)
    row = stats.set_index("address_id").loc["A"]
    assert row["one_hop_neighbor_count"] == 1 and row["one_hop_avg_risk"] == 80


@pytest.mark.parametrize("address", ["../../escape", "CON", "A/B", "C:\\secret", "", "A"*200])
def test_artifact_paths_cannot_escape(address):
    name = artifact_key(address)
    assert "/" not in name and "\\" not in name and ":" not in name
    assert name and name != "CON"


def test_real_bitcoin_ids_remain_readable():
    address = "1ABCdef123"
    assert artifact_key(address) == address
