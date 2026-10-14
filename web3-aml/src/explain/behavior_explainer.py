from pathlib import Path
import numpy as np
import torch
from torch import nn
from captum.attr import IntegratedGradients
from src.inference.precompute_scores import load_model
from src.model.feature_transform import transform_features
from src.utils.io import ROOT, load_config, read_json


class BehaviorLogit(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, x):
        return self.model.behavior_head(self.model.encode_behavior(x)).flatten()


class BehaviorExplainer:
    def __init__(self, root: Path = ROOT):
        self.model, self.config = load_model(root)
        self.model.eval()
        self.x = np.load(root / "data/processed/features.npy", mmap_mode="r")
        self.raw = np.load(root / "data/processed/raw_features.npy", mmap_mode="r")
        if self.config.get("input_transform"):
            self.x = transform_features(self.raw, self.config["input_transform"])
        self.features = read_json(root / "data/processed/feature_names.json")
        self.names = load_config("feature_names.yaml", root)["feature_names"] or {}
        self.ig = IntegratedGradients(BehaviorLogit(self.model))

    def explain(self, node_idx):
        settings = self.config["explanation"]
        x = torch.from_numpy(np.array(self.x[node_idx:node_idx+1], copy=True))
        attribution, delta = self.ig.attribute(x, baselines=torch.zeros_like(x),
                                               n_steps=settings["ig_steps"], return_convergence_delta=True)
        attribution = attribution.detach().numpy()[0]
        top = np.argsort(-np.abs(attribution))[:settings["top_k"]]
        return [{"feature": self.names.get(self.features[i], self.features[i]), "raw_feature": self.features[i],
                 "feature_value": float(self.raw[node_idx, i]) if np.isfinite(self.raw[node_idx, i]) else None,
                 "standardized_value": float(self.x[node_idx, i]), "contribution": float(attribution[i]),
                 "direction": "increases_behavior_logit" if attribution[i] >= 0 else "decreases_behavior_logit",
                 "attribution_target": "behavior_head_logit",
                 "baseline": "training_transformed_mean_zero" if self.config.get("input_transform") else "training_mean_standardized_zero",
                 "convergence_delta": float(delta.item())} for i in top]
