"""Explicit direction statistics; no address features, risk scores or labels."""
import numpy as np
from scipy.sparse import csr_matrix
from src.model.topology_features import topology_features, NAMES

EXTRA_NAMES = [
    "mean_downstream_log_in_degree", "mean_downstream_log_out_degree",
    "mean_upstream_log_in_degree", "mean_upstream_log_out_degree",
    "mean_downstream_direction_balance", "mean_upstream_direction_balance",
    "downstream_sink_fraction", "upstream_source_fraction",
    "log_forward_two_step_walks", "log_backward_two_step_walks",
]
STRUCTURE_NAMES = NAMES + EXTRA_NAMES


def directed_structure(edges, num_nodes, timesteps=None, cutoff=None):
    base = topology_features(edges, num_nodes, timesteps, cutoff)
    src, dst = np.asarray(edges)
    keep = src != dst
    if cutoff is not None:
        if timesteps is None:
            raise ValueError("Temporal structure needs timesteps")
        eligible = np.asarray(timesteps) <= cutoff
        keep &= eligible[src] & eligible[dst]
    matrix = csr_matrix((np.ones(keep.sum(), dtype=np.float32), (src[keep], dst[keep])),
                        shape=(num_nodes, num_nodes))
    matrix.data[:] = 1
    out_degree = np.asarray(matrix.sum(axis=1)).ravel()
    in_degree = np.asarray(matrix.sum(axis=0)).ravel()
    reciprocal = np.asarray(matrix.multiply(matrix.T).sum(axis=1)).ravel()
    def average(direction, value, degree):
        return np.asarray(direction @ value).ravel()/np.maximum(degree, 1)
    extras = [
        average(matrix, np.log1p(in_degree), out_degree),
        average(matrix, np.log1p(out_degree), out_degree),
        average(matrix.T, np.log1p(in_degree), in_degree),
        average(matrix.T, np.log1p(out_degree), in_degree),
        average(matrix, base[:, 3], out_degree),
        average(matrix.T, base[:, 3], in_degree),
        average(matrix, (out_degree == 0).astype(np.float32), out_degree),
        average(matrix.T, (in_degree == 0).astype(np.float32), in_degree),
        np.log1p(np.maximum(np.asarray(matrix @ out_degree).ravel()-reciprocal, 0)),
        np.log1p(np.maximum(np.asarray(matrix.T @ in_degree).ravel()-reciprocal, 0)),
    ]
    result = np.column_stack([base, *extras]).astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("Non-finite structure statistics")
    return result
