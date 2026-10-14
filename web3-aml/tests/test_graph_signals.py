import numpy as np
from src.model.graph_signals import adjacency_operators, signal_blocks
from src.train.role_experiments import validate_routes
import pytest


def test_signals_have_direction_and_beta_reconstructs_input():
    edges = np.array([[0, 0, 1], [1, 2, 2]])
    x = np.array([[1, 4], [3, 2], [5, 0]], dtype=np.float32)
    operators = adjacency_operators(edges, 3)
    blocks = dict(signal_blocks(x, operators))
    assert np.allclose(blocks['out1'][0], [4, 1])
    assert np.allclose(blocks['in1'][0], [0, 0])
    assert np.allclose(blocks['beta_low']+2*blocks['beta_mid']+blocks['beta_high'], x, atol=1e-6)
    assert np.allclose(blocks['out_residual'], x-blocks['out1'])
    assert all(np.isfinite(v).all() for v in blocks.values())


def test_future_nodes_do_not_influence_past_signal():
    edges = np.array([[0, 1], [1, 2]])
    x = np.array([[1], [2], [999]], dtype=np.float32)
    op = adjacency_operators(edges, 3, np.array([1, 2, 3]), cutoff=2)
    assert np.allclose(op['out'] @ x, [[2], [0], [0]])
    assert np.allclose(op['in'] @ x, [[0], [1], [0]])


def test_a_candidate_cannot_hide_a_duplicate_graphsage():
    validate_routes(['behavior', 'graphsage', 'structure18'])
    with pytest.raises(ValueError, match='duplicate'):
        validate_routes(['dual_view', 'graphsage', 'structure18'])
