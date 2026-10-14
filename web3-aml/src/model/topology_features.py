"""Label-free directed topology, with chronological node eligibility."""
import numpy as np
from scipy.sparse import csr_matrix

NAMES = ["log_in_degree", "log_out_degree", "log_neighbor_count", "flow_balance",
         "reciprocal_ratio", "mean_downstream_log_degree", "mean_upstream_log_degree",
         "is_isolated"]


def topology_features(edges, num_nodes, timesteps=None, cutoff=None):
    edges = np.asarray(edges)
    src, dst = edges
    valid = src != dst
    if cutoff is not None:
        if timesteps is None:
            raise ValueError("Temporal topology needs timesteps.")
        eligible = np.asarray(timesteps) <= cutoff
        valid &= eligible[src] & eligible[dst]
    src, dst = src[valid], dst[valid]
    matrix = csr_matrix((np.ones(len(src), dtype=np.float32), (src, dst)), shape=(num_nodes, num_nodes))
    matrix.data[:] = 1  # collapse duplicate relation edges
    outward = np.asarray(matrix.sum(axis=1)).ravel()
    inward = np.asarray(matrix.sum(axis=0)).ravel()
    union = matrix.maximum(matrix.T)
    neighbors = np.asarray(union.sum(axis=1)).ravel()
    degree_log = np.log1p(neighbors)
    reciprocal = inward + outward - neighbors
    result = np.column_stack([
        np.log1p(inward), np.log1p(outward), degree_log,
        (outward-inward)/np.maximum(outward+inward, 1),
        reciprocal/np.maximum(neighbors, 1),
        np.asarray(matrix @ degree_log).ravel()/np.maximum(outward, 1),
        np.asarray(matrix.T @ degree_log).ravel()/np.maximum(inward, 1),
        (neighbors == 0).astype(np.float32),
    ]).astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("Non-finite topology features.")
    return result
