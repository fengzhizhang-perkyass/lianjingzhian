import numpy as np
import pytest
from src.model.directed_structure import directed_structure, STRUCTURE_NAMES


def test_direction_exposes_fanout_and_fanin_without_second_graph_encoder():
    edges = np.array([[0, 0, 1, 2], [1, 2, 3, 3]])
    x = directed_structure(edges, 4)
    assert x.shape == (4, len(STRUCTURE_NAMES))
    assert x[0, 3] == 1 and x[3, 3] == -1
    assert x[0, -2] == pytest.approx(np.log(3))
    assert x[3, -1] == pytest.approx(np.log(3))
    assert x[1, -4] == 1 and x[1, -3] == 1
    reverse = directed_structure(edges[::-1], 4)
    assert np.allclose(x[:, 3], -reverse[:, 3])
    assert np.allclose(x[:, -2], reverse[:, -1])


def test_structure_filters_future_edges_and_collapses_duplicate_self_edges():
    edges = np.array([[0, 0, 1, 1, 2], [1, 1, 1, 2, 3]])
    times = np.array([1, 2, 3, 4])
    x = directed_structure(edges, 4, times, 2)
    expected = directed_structure(np.array([[0], [1]]), 4)
    assert np.allclose(x, expected)
    assert np.isfinite(x).all()
