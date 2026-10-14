import torch
from torch import nn
from .behavior_encoder import BehaviorEncoder
from .graph_encoder import GraphEncoder
from .fusion import GatedFusion


class DualViewModel(nn.Module):
    def __init__(self, input_dim, config, mode="dual_view"):
        super().__init__()
        if mode not in {"dual_view", "behavior", "graphsage"}:
            raise ValueError(f"Unsupported model mode: {mode}")
        self.mode = mode
        self.embedding_dim = config["embedding_dim"]
        self.behavior_encoder = BehaviorEncoder(input_dim, config["behavior_hidden"],
                                                self.embedding_dim, config["dropout"])
        self.graph_encoder = GraphEncoder(input_dim, config["graph_hidden"],
                                          self.embedding_dim, config["dropout"])
        normalization = config.get("embedding_normalization", "none")
        if normalization not in {"none", "layernorm"}:
            raise ValueError("embedding_normalization must be none or layernorm")
        self.behavior_norm = nn.LayerNorm(self.embedding_dim) if normalization == "layernorm" else nn.Identity()
        self.graph_norm = nn.LayerNorm(self.embedding_dim) if normalization == "layernorm" else nn.Identity()
        self.fusion = GatedFusion(self.embedding_dim, config.get("fusion_mode", "learned"),
                                 config.get("fixed_behavior_weight", 0.5))
        self.behavior_head = nn.Linear(self.embedding_dim, 1)
        self.graph_head = nn.Linear(self.embedding_dim, 1)
        self.fusion_head = nn.Linear(self.embedding_dim, 1)

    def encode_behavior(self, x):
        return self.behavior_norm(self.behavior_encoder(x))

    def encode_graph(self, x, edge_index):
        return self.graph_norm(self.graph_encoder(x, edge_index))

    def forward(self, x, edge_index):
        blank = x.new_zeros((len(x), self.embedding_dim))
        behavior = self.encode_behavior(x) if self.mode != "graphsage" else blank
        graph = self.encode_graph(x, edge_index) if self.mode != "behavior" else blank
        if self.mode == "behavior":
            fused, gate = behavior, x.new_ones((len(x), 1))
        elif self.mode == "graphsage":
            fused, gate = graph, x.new_zeros((len(x), 1))
        else:
            fused, gate = self.fusion(behavior, graph)
        return {"behavior_logits": self.behavior_head(behavior).flatten(),
                "graph_logits": self.graph_head(graph).flatten(),
                "fused_logits": self.fusion_head(fused).flatten(), "gate": gate.flatten()}
