"""Precomputed graph signals inspired by SIGN, Dir-GNN and beta-wavelet filters.

This is a tree-based adaptation, not a reproduction of the source neural models.
All operators are label-free, deterministic, direction preserving where named.
"""
import numpy as np
from scipy.sparse import csr_matrix


def adjacency_operators(edges, num_nodes, timesteps=None, cutoff=None):
    src, dst = np.asarray(edges)
    keep = src != dst
    if cutoff is not None:
        if timesteps is None:
            raise ValueError("Temporal operators require timesteps")
        eligible = np.asarray(timesteps) <= cutoff
        keep &= eligible[src] & eligible[dst]
    a = csr_matrix((np.ones(keep.sum(), dtype=np.float32), (src[keep], dst[keep])), shape=(num_nodes, num_nodes))
    a.data[:] = 1
    inward = a.T.tocsr()
    union = a.maximum(inward).tocsr()
    def row_normalize(matrix):
        degree = np.asarray(matrix.sum(axis=1)).ravel()
        return matrix.multiply((1/np.maximum(degree, 1))[:, None]).tocsr()
    degree = np.asarray(union.sum(axis=1)).ravel()
    inv = np.zeros_like(degree)
    np.divide(1, np.sqrt(degree), out=inv, where=degree > 0)
    symmetric = union.multiply(inv[:, None]).multiply(inv[None, :]).tocsr()
    return {"out": row_normalize(a), "in": row_normalize(inward),
            "union": row_normalize(union), "symmetric": symmetric}


def signal_blocks(x, operators):
    """Yield one block at a time to bound memory on large CPU graphs."""
    x = np.asarray(x, dtype=np.float32)
    yield "self", x
    for direction in ("out", "in", "union"):
        first = np.asarray(operators[direction] @ x, dtype=np.float32)
        yield direction+"1", first
        yield direction+"2", np.asarray(operators[direction] @ first, dtype=np.float32)
        if direction != "union":
            yield direction+"_residual", x-first
    first = np.asarray(operators["symmetric"] @ x, dtype=np.float32)
    second = np.asarray(operators["symmetric"] @ first, dtype=np.float32)
    # L = I-S; degree-two beta filters, with common constants omitted.
    # The original BWGNN also learns neural transformations: not included here.
    yield "beta_low", .25*(x+2*first+second)
    yield "beta_mid", .25*(x-second)
    yield "beta_high", .25*(x-2*first+second)
