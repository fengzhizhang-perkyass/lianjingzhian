import pytest
from src.tracing.graph_loader import DirectedGraph
from src.tracing.beam_search import RiskGuidedTracer
from src.tracing.path_scorer import expand_score
from src.utils.io import load_config


def tracer():
    mapping = {a: i for i, a in enumerate("ABCDE")}
    graph = DirectedGraph({0: [1, 2], 1: [3], 2: [4], 3: [0]},
                          {1: [0], 2: [0], 3: [1], 4: [2], 0: [3]}, mapping,
                          {str(i): a for a, i in mapping.items()})
    return RiskGuidedTracer(graph, dict(A=95, B=95, C=10, D=92, E=5), load_config("tracing.yaml"))


def test_high_risk_chain_direction_and_cycles():
    result = tracer().trace("A", {"max_depth": 4})
    assert any(p["nodes"] == ["A", "B", "D"] for p in result["top_paths"])
    assert all("C" not in p["nodes"] for p in result["top_paths"])
    assert all(len(p["nodes"]) == len(set(p["nodes"])) for p in result["top_paths"])
    assert result["statistics"]["max_reached_depth"] == 2


def test_depth_threshold_and_beam_limits():
    result = tracer().trace("A", {"max_depth": 1, "beam_width": 1})
    assert result["top_paths"][0]["nodes"] == ["A", "B"]
    assert not tracer().trace("A", {"risk_threshold": 100})["top_paths"]
    with pytest.raises(ValueError):
        tracer().trace("A", {"max_depth": 0})
    assert expand_score(95, 90, 0, 0, {"risk": .75, "neighbor_risk": .15, "degree_penalty": .1}) > 0


def test_deterministic_trace():
    instance = tracer()
    assert instance.trace("A") == instance.trace("A")
