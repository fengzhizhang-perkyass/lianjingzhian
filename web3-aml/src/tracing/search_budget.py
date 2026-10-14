"""Per-request accounting: repeated adjacency reads also cost one inspection."""
from collections import Counter


class SearchBudget:
    def __init__(self, limit):
        self.limit = limit
        self.counts = Counter()
        self.total = 0
        self.denied = False

    def consume(self, stage, stage_limit=None):
        if self.total >= self.limit:
            self.denied = True
            return False
        if stage_limit is not None and self.counts[stage] >= stage_limit:
            return False
        self.total += 1
        self.counts[stage] += 1
        return True

    def scan(self, graph, address, stage, stage_limit=None):
        # Degree lookup is O(1); do not fetch the next edge after budget exhaustion.
        degree = graph.degrees(address)[0]
        edges = graph.iter_out_neighbors(address)
        for _ in range(degree):
            if not self.consume(stage, stage_limit):
                break
            yield next(edges)
