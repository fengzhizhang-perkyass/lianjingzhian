"""Native LightGBM TreeSHAP explains the topology expert, not the entire ensemble."""
import joblib
import numpy as np
from src.model.feature_transform import transform_features
from src.model.topology_features import NAMES
from src.utils.io import read_json

DISPLAY_NAMES = {
    "log_in_degree": "入度对数", "log_out_degree": "出度对数", "log_neighbor_count": "邻居数量对数",
    "flow_balance": "出入方向平衡", "reciprocal_ratio": "双向邻居比例",
    "mean_downstream_log_degree": "下游平均连接度对数", "mean_upstream_log_degree": "上游平均连接度对数",
    "is_isolated": "是否孤立节点",
}


class TopologyTreeExplainer:
    def __init__(self, root, metadata):
        folder = root / "artifacts/experiments" / metadata["experiment"] / f"final/seed_{metadata['seed']}/topology_tree"
        self.model = joblib.load(folder / "model.pkl")
        self.state = read_json(folder / "input_transform.json")
        self.raw = np.load(root / "data/processed/raw_features.npy", mmap_mode="r")
        self.structure = np.load(root / "artifacts/investigation/topology_features.npy", mmap_mode="r")
        self.names = read_json(root / "data/processed/feature_names.json")+NAMES

    def explain(self, node_idx, top_k=5):
        x = np.concatenate([transform_features(self.raw[node_idx:node_idx+1], self.state), self.structure[node_idx:node_idx+1]], axis=1)
        attribution = self.model.booster_.predict(x, pred_contrib=True)[0]
        raw_margin = float(self.model.booster_.predict(x, raw_score=True)[0])
        residual = float(attribution.sum()-raw_margin)
        top = np.argsort(-np.abs(attribution[:-1]))[:top_k]
        return [{"feature": DISPLAY_NAMES.get(self.names[i], self.names[i]), "raw_feature": self.names[i],
                 "model_input_value": float(x[0, i]), "contribution": float(attribution[i]),
                 "attribution_target": "topology_tree_raw_margin", "additivity_residual": residual}
                for i in top]
