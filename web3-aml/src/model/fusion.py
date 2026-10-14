import torch
from torch import nn


class GatedFusion(nn.Module):
    def __init__(self, embedding_dim=64, mode="learned", fixed_weight=0.5):
        super().__init__()
        if mode not in {"learned", "fixed"} or not 0 <= fixed_weight <= 1:
            raise ValueError("Invalid fusion mode or fixed weight.")
        self.mode, self.fixed_weight = mode, fixed_weight
        self.gate = nn.Linear(embedding_dim * 2, 1)

    def forward(self, behavior, graph):
        gate = (torch.sigmoid(self.gate(torch.cat((behavior, graph), dim=-1)))
                if self.mode == "learned" else behavior.new_full((len(behavior), 1), self.fixed_weight))
        return gate * behavior + (1-gate) * graph, gate
