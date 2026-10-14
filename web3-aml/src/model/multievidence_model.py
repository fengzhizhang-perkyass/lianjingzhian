"""Pointwise encoders over precomputed evidence; no GraphSAGE or sampling."""
import torch
from torch import nn


class MultiEvidenceModel(nn.Module):
    def __init__(self, input_dims, hidden_dim=128, embedding_dim=64, dropout=.2, fusion='gated'):
        super().__init__()
        if not input_dims or fusion not in {'gated', 'concat'}:
            raise ValueError('Invalid evidence routes or fusion')
        self.fusion = fusion
        self.encoders = nn.ModuleList([nn.Sequential(nn.Linear(d, hidden_dim), nn.ReLU(), nn.Dropout(dropout),
                                                    nn.Linear(hidden_dim, embedding_dim), nn.ReLU()) for d in input_dims])
        self.heads = nn.ModuleList([nn.Linear(embedding_dim, 1) for _ in input_dims])
        self.gate = nn.Linear(embedding_dim*len(input_dims), len(input_dims))
        self.fused_head = nn.Linear(embedding_dim if fusion == 'gated' else embedding_dim*len(input_dims), 1)

    def forward(self, inputs):
        embeddings = [encoder(x) for encoder, x in zip(self.encoders, inputs)]
        combined = torch.cat(embeddings, dim=1)
        weights = self.gate(combined).softmax(dim=1)
        fused = (torch.stack(embeddings, dim=1)*weights.unsqueeze(-1)).sum(dim=1) if self.fusion == 'gated' else combined
        return {'logits': self.fused_head(fused).squeeze(-1),
                'route_logits': torch.cat([head(x) for head, x in zip(self.heads, embeddings)], dim=1),
                'weights': weights}
