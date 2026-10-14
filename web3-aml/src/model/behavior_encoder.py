from torch import nn


class BehaviorEncoder(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, out_dim=64, dropout=0.2):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(input_dim, hidden_dim), nn.ReLU(),
                                    nn.Dropout(dropout), nn.Linear(hidden_dim, out_dim), nn.ReLU())

    def forward(self, x):
        return self.layers(x)
