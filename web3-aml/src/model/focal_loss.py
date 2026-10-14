import torch
from torch import nn
from torch.nn import functional as F


class FocalLoss(nn.Module):
    def __init__(self, alpha=0.75, gamma=2.0):
        super().__init__()
        self.alpha, self.gamma = alpha, gamma

    def forward(self, logits, targets):
        targets = targets.float()
        bce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        pt = torch.exp(-bce)
        alpha = torch.where(targets == 1, self.alpha, 1-self.alpha)
        return (alpha * (1-pt).pow(self.gamma) * bce).mean()
