import numpy as np
import torch
from torch.nn import functional as F


@torch.no_grad()
def correct_weighted_bce_heads(model, positive_weight):
    """Undo the analytic odds multiplier of positive-weighted binary CE.

    Exported linear heads retain the original architecture. This is a constant
    bias correction, not a fitted calibrator; temperature still fits on validation.
    """
    if not np.isfinite(positive_weight) or positive_weight <= 0:
        raise ValueError("Positive class weight must be finite and positive.")
    offset = float(np.log(positive_weight))
    for head in (model.behavior_head, model.graph_head, model.fusion_head):
        head.bias.sub_(offset)
    return {"method": "weighted_bce_odds_correction", "positive_weight": float(positive_weight), "logit_offset": offset}


def weighted_probability_logits(probabilities, positive_weight):
    """Convert class-weighted probabilities back to unweighted log odds."""
    if positive_weight <= 0 or not np.isfinite(positive_weight):
        raise ValueError("Positive class weight must be finite and positive.")
    probabilities = np.asarray(probabilities, dtype=np.float64)
    eps = np.finfo(np.float64).eps
    probabilities = np.clip(probabilities, eps, 1-eps)
    return np.log(probabilities) - np.log1p(-probabilities) - np.log(positive_weight)


def fit_temperature(logits, labels, max_iter=50):
    z, y = torch.as_tensor(logits, dtype=torch.float64), torch.as_tensor(labels, dtype=torch.float64)
    log_t = torch.zeros(1, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS([log_t], lr=0.1, max_iter=max_iter, line_search_fn="strong_wolfe")

    def closure():
        optimizer.zero_grad()
        temperature = log_t.exp().clamp(0.05, 20)
        loss = F.binary_cross_entropy_with_logits(z/temperature, y)
        loss.backward()
        return loss

    optimizer.step(closure)
    return float(log_t.exp().clamp(0.05, 20).detach())


def calibrated_probability(logits, temperature):
    if temperature <= 0:
        raise ValueError("Temperature must be positive.")
    return torch.sigmoid(torch.as_tensor(np.asarray(logits), dtype=torch.float64)/temperature).numpy()
