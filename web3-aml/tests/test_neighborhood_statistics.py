import numpy as np
import pytest
from src.model.graph_signals import adjacency_operators
from src.model.neighborhood_statistics import neighborhood_statistics


def test_neighborhood_dispersion_zscore_and_empty_neighbors():
    x = np.array([[9], [2], [4]], dtype=np.float32)
    op = adjacency_operators(np.array([[0, 0], [1, 2]]), 3)
    blocks = dict(neighborhood_statistics(x, op, std_floor=.5, clip=8))
    assert blocks['out_std'][0, 0] == pytest.approx(1)
    assert blocks['out_zscore'][0, 0] == pytest.approx(6)
    assert blocks['out_zscore'][1, 0] == 0
    assert blocks['in_zscore'][1, 0] == -8
    assert all(np.isfinite(v).all() for v in blocks.values())


def test_statistics_require_positive_scale():
    with pytest.raises(ValueError):
        list(neighborhood_statistics(np.ones((1, 1)), {}, std_floor=0))
