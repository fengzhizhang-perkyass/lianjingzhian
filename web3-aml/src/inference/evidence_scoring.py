"""Online TreeSHAP for the actual joint decision; no online graph inference."""
import joblib
import numpy as np
from src.utils.io import read_json
from src.explain.topology_explainer import DISPLAY_NAMES

ROLES = {
    'behavior': ('行为画像', '地址自身的交易规模、频次、费用和活跃节奏'),
    'context': ('方向邻域偏离', '与上游、下游地址行为的相对差异，保留被均值掩盖的异常'),
    'structure': ('有向结构角色', '汇入、分出、双向关联和上下游连接模式'),
}


class EvidenceScoringExplainer:
    def __init__(self, root, metadata):
        self.root, self.metadata = root, metadata
        self.model = joblib.load(root / metadata['model_path'])
        self.info = read_json(root / metadata['validation_path'])
        self.x = np.load(root / metadata['features_path'], mmap_mode='r')
        self.raw = np.load(root / 'data/processed/raw_features.npy', mmap_mode='r')
        self.raw_names = read_json(root / 'data/processed/feature_names.json')
        from src.utils.io import load_config
        self.names = load_config('feature_names.yaml', root)['feature_names'] or {}

    def explain(self, node_idx, route_scores, top_k=5):
        x = np.array(self.x[node_idx:node_idx+1], copy=True)
        attribution = self.model.booster_.predict(x, pred_contrib=True)[0]
        margin = float(self.model.booster_.predict(x, raw_score=True)[0])
        residual = float(attribution.sum()-margin)
        if abs(residual) > 1e-5:
            raise RuntimeError('TreeSHAP did not reconstruct the joint model output')
        groups, evidence = [], {}
        total_abs = float(np.abs(attribution[:-1]).sum())
        for group, (label, responsibility) in ROLES.items():
            ids = [i for i, item in enumerate(self.info['schema']) if item['group'] == group]
            groups.append({'key': group, 'label': label, 'responsibility': responsibility,
                           'contribution': float(attribution[ids].sum()),
                           'absolute_contribution_share': float(np.abs(attribution[ids]).sum()/max(total_abs, 1e-12))})
            chosen = sorted(ids, key=lambda i: -abs(attribution[i]))[:top_k]
            items = []
            for i in chosen:
                schema = self.info['schema'][i]
                feature = schema['feature']
                label_feature = self.names.get(feature, DISPLAY_NAMES.get(feature, feature))
                if schema['block'] != 'self' and schema['block'] != 'structure':
                    prefix = '下游' if schema['block'].startswith('out') else '上游'
                    label_feature = prefix+'标准化偏离 · '+label_feature
                raw_value = self.raw[node_idx, self.raw_names.index(feature)] if schema['block'] == 'self' else None
                items.append({'feature': label_feature, 'raw_feature': feature,
                              'feature_value': float(raw_value) if raw_value is not None and np.isfinite(raw_value) else None,
                              'model_input_value': float(x[0, i]), 'contribution': float(attribution[i]),
                              'direction': 'increases_joint_margin' if attribution[i] >= 0 else 'decreases_joint_margin',
                              'attribution_target': 'joint_tree_raw_margin', 'additivity_residual': residual})
            evidence[group] = items
        return {'model_name': self.metadata['model_name'], 'model_version': self.metadata['model_version'],
                'fusion': 'joint_feature_fusion', 'route_scores': route_scores,
                'route_score_purpose': '独立单类证据模型用于诊断；联合模型输入特征，不平均这些分数',
                'groups': groups, 'evidence': evidence, 'base_value': float(attribution[-1]),
                'raw_margin': margin, 'corrected_logit': margin-float(np.log(self.info['positive_weight'])),
                'temperature': self.info['temperature'], 'additivity_residual': residual,
                'revision': self.metadata['risk_revision']}
