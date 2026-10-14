"""Budget-limited directed unweighted local push, inspired by APPR/TRacer.

Partial pushes retain unprocessed probability as residual. This is not TRacer's
weighted temporal multi-relation transition model, nor an exact full-graph PPR.
"""
import heapq
import math
from collections import defaultdict


def local_push(graph, seed, budget, limit, restart, tolerance, max_pushes):
    settled, residual = defaultdict(float), defaultdict(float)
    residual[seed] = 1.0
    queue = [(-1.0, seed)]
    pushes = 0
    while queue and pushes < max_pushes:
        negative_mass, address = heapq.heappop(queue)
        mass = residual[address]
        if not math.isclose(-negative_mass, mass, rel_tol=1e-12, abs_tol=1e-15):
            continue
        if mass < tolerance:
            break
        if budget.counts['ppr'] >= limit or budget.total >= budget.limit:
            break
        pushes += 1
        residual[address] = 0.0
        settled[address] += restart * mass
        degree = graph.degrees(address)[0]
        remaining = (1-restart) * mass
        if degree == 0:
            residual[seed] += remaining
            heapq.heappush(queue, (-residual[seed], seed))
            continue
        count = 0
        share = remaining / degree
        for neighbor in budget.scan(graph, address, 'ppr', limit):
            count += 1
            residual[neighbor] += share
            heapq.heappush(queue, (-residual[neighbor], neighbor))
        if count < degree:
            residual[address] += share * (degree-count)
            break
    total_residual = sum(residual.values())
    normalization = max((value for address, value in settled.items() if address != seed), default=0)
    scores = {address: value/normalization for address, value in settled.items()
              if address != seed and normalization > 0}
    return scores, {'settled_mass': sum(settled.values()), 'residual_mass': total_residual,
                    'pushes': pushes, 'edge_inspections': budget.counts['ppr'],
                    'converged': total_residual <= tolerance,
                    'transition_model': 'directed_unweighted_dangling_restart',
                    'approximation': 'budget_limited_local_push'}
