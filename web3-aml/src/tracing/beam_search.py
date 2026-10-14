from pathlib import Path
import numpy as np
from src.tracing.path_scorer import expand_score, path_score
from src.utils.io import ROOT, save_json, artifact_key


class RiskGuidedTracer:
    def __init__(self, graph, risk_scores, config, graph_statistics=None):
        self.graph, self.risks, self.config = graph, risk_scores, dict(config)
        self.graph_statistics = graph_statistics or {}
        self.degree_p99 = float(np.percentile([sum(graph.degrees(a)) for a in risk_scores], 99)) if risk_scores else 0
        self._expand_cache = {}

    def expansion(self, address):
        if address not in self._expand_cache:
            stats = self.graph_statistics.get(address)
            if stats is not None:
                neighbor_risk = stats["one_hop_avg_risk"]
            else:
                neighbors = self.graph.neighbors(address)
                neighbor_risk = float(np.mean([self.risks[a] for a in neighbors])) if neighbors else 0
            self._expand_cache[address] = expand_score(self.risks[address], neighbor_risk,
                sum(self.graph.degrees(address)), self.degree_p99, self.config["score_weight"])
        return self._expand_cache[address]

    def trace(self, seed, overrides=None):
        if seed not in self.risks:
            raise KeyError(f"Unknown seed: {seed}")
        config = {**self.config, **(overrides or {})}
        for key in ("max_depth", "beam_width", "max_neighbors_per_node", "top_paths"):
            if not isinstance(config[key], int) or config[key] < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not 0 <= config["risk_threshold"] <= 100:
            raise ValueError("risk_threshold must be within [0,100]")
        beam = [([seed], [], 0.0)]
        completed, considered, retained, pruned_events = [], set(), {seed}, 0
        for _ in range(config["max_depth"]):
            candidates = []
            for nodes, scores, _ in beam:
                neighbors = self.graph.out_neighbors(nodes[-1])
                considered.update(neighbors)
                neighbors = sorted(neighbors, key=lambda a: (-self.risks[a], a))
                pruned_events += max(0, len(neighbors)-config["max_neighbors_per_node"])
                for address in neighbors[:config["max_neighbors_per_node"]]:
                    if (config["cycle_check"] and address in nodes) or self.risks[address] < config["risk_threshold"]:
                        pruned_events += 1
                        continue
                    new_scores = scores + [self.expansion(address)]
                    candidates.append((nodes+[address], new_scores, path_score(new_scores, config["length_decay"])))
            if not candidates:
                break
            candidates.sort(key=lambda p: (-p[2], tuple(p[0])))
            beam = candidates[:config["beam_width"]]
            pruned_events += max(0, len(candidates)-len(beam))
            for nodes, _, _ in beam:
                retained.update(nodes)
            completed.extend(beam)
        completed.sort(key=lambda p: (-p[2], tuple(p[0])))
        unique, seen = [], set()
        for item in completed:
            key = tuple(item[0])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        paths = [{"rank": rank+1, "nodes": nodes, "node_risks": [float(self.risks[a]) for a in nodes],
                  "path_score": float(score), "hop_count": len(nodes)-1}
                 for rank, (nodes, _, score) in enumerate(unique[:config["top_paths"]])]
        nodes_in_view = {seed} | {a for p in paths for a in p["nodes"]}
        view = {"nodes": [{"address_id": a, "risk_score": float(self.risks[a]), "is_seed": a == seed}
                           for a in sorted(nodes_in_view)],
                "edges": [{"src": src, "dst": dst, "path_rank": p["rank"]}
                          for p in paths for src, dst in zip(p["nodes"], p["nodes"][1:])]}
        return {"seed_address": seed, "config": config,
                "statistics": {"visited_nodes": len(retained), "candidate_nodes": len(considered-{seed}),
                               "high_risk_nodes": sum(self.risks[a] >= config["high_risk_threshold"] for a in retained-{seed}),
                               "pruned_nodes": len(considered-retained), "pruned_expansions": pruned_events,
                               "max_reached_depth": max((len(p[0])-1 for p in completed), default=0)},
                "top_paths": paths, "subgraph": view}

    def save(self, result, root: Path = ROOT):
        save_json(root / "artifacts/traces" / f"{artifact_key(result['seed_address'])}.json", result)
