from torch import nn
from torch_geometric.nn import SAGEConv


class GraphEncoder(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, out_dim=64, dropout=0.2):
        super().__init__()
        self.conv1 = SAGEConv(input_dim, hidden_dim)
        self.conv2 = SAGEConv(hidden_dim, out_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, edge_index):
        return self.conv2(self.dropout(self.conv1(x, edge_index).relu()), edge_index)
