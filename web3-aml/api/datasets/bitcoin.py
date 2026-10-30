"""B3 on all1783 frozen evidence columns, with actual native TreeSHAP."""
import gzip
import shutil
from pathlib import Path

import numpy as np
from api.datasets.base import DatasetService
from src.inference.native_tree import load_native_tree
from src.utils.io import read_json, load_config, file_sha256


GROUPS = {
    'behavior': ('交易行为画像', '描述地址自身的交易规模、频率和活跃习惯。'),
    'context': ('邻域行为偏离', '描述地址与关联地址之间的行为差异。'),
    'structure': ('资金流转特征', '描述资金收支方向、汇聚分散情况及关联交易属性。'),
}


def _materialize_features(path: Path) -> None:
    """Decompress the shipped .gz asset when the mmap target is missing."""
    gz_path = Path(str(path) + '.gz')
    if path.is_file() or not gz_path.is_file():
        return
    with gzip.open(gz_path, 'rb') as source, open(path, 'wb') as target:
        shutil.copyfileobj(source, target)


class BitcoinService(DatasetService):
    def __init__(self, root):
        folder = Path(root)/'artifacts/datasets/bitcoin/current'
        if not (folder/'manifest.json').is_file():
            raise FileNotFoundError('比特币运行产物尚未准备，请先运行 python scripts/prepare_v3_runtime.py --dataset bitcoin。')
        super().__init__(root, 'bitcoin', folder)
        _materialize_features(self.root/self.manifest['features_path'])
        for field in ('features_path', 'model_path'):
            relative = self.manifest[field]
            if file_sha256(self.root/relative) != self.manifest['source_hashes'][relative]:
                raise ValueError('比特币模型或特征与冻结运行清单不一致：'+field)
        self.features = np.load(self.root/self.manifest['features_path'], mmap_mode='r')
        self.schema = read_json(self.folder/'schema.json')
        self.model = load_native_tree(self.root/self.manifest['model_path'], backend='lightgbm_joblib', expected_features=1783)
        self.raw = np.load(self.root/'data/processed/raw_features.npy', mmap_mode='r')
        self.raw_names = read_json(self.root/'data/processed/feature_names.json')
        self.names = load_config('feature_names.yaml', self.root).get('feature_names') or {}

    def analyze(self, address):
        lookup = self.predictor.lookup(address)
        i = lookup['node_idx']
        x = np.asarray(self.features[i:i+1])
        shap = self.model.tree_shap(x)[0]
        margin = float(self.model.raw_margin(x)[0])
        probability = float(self.model.predict_probability(x)[0])
        if abs(probability-lookup['risk']['raw_probability']) > 1e-12:
            raise RuntimeError('Risk cache and real model output disagree')
        total = float(np.abs(shap[:-1]).sum())
        groups, evidence = [], {}
        for key, (label, responsibility) in GROUPS.items():
            ids = [j for j, item in enumerate(self.schema) if item['group'] == key]
            groups.append({'key': key, 'label': label, 'responsibility': responsibility,
                           'contribution': float(shap[ids].sum()),
                           'absolute_contribution_share': float(np.abs(shap[ids]).sum()/max(total, 1e-12))})
            items = []
            for j in sorted(ids, key=lambda k: -abs(shap[k]))[:5]:
                col = self.schema[j]
                feature = col['feature']
                display = col.get('display_name') or self.names.get(feature, feature)
                if not col.get('display_name') and col['block'] not in ('self', 'structure'):
                    display = ('下游' if col['block'].startswith('out') else '上游')+'关联统计 · '+display
                raw = (float(self.raw[i, self.raw_names.index(feature)])
                       if col['block'] == 'self' and feature in self.raw_names else None)
                items.append({'feature': display, 'raw_feature': feature, 'feature_value': raw,
                    'model_input_value': float(x[0, j]), 'contribution': float(shap[j]),
                    'direction': 'increases_joint_margin' if shap[j] >= 0 else 'decreases_joint_margin',
                    'attribution_target': 'joint_tree_raw_margin', 'additivity_residual': float(shap.sum()-margin)})
            evidence[key] = items
        scoring = {'kind': 'grouped_tree', 'model_name': self.manifest['model_display_name'],
            'groups': groups, 'evidence': evidence, 'base_value': float(shap[-1]), 'raw_margin': margin,
            'corrected_logit': margin, 'temperature': 1., 'additivity_residual': float(shap.sum()-margin),
            'route_scores': {}, 'revision': self.metadata['risk_revision'],
            'fusion': 'joint_feature_tree', 'feature_count': 1783, 'model_threshold': self.manifest['model_threshold'],
            'calibration': self.calibration.describe(probability),
            'route_score_purpose': '按真实特征贡献分组，不是独立风险分或概率平均。'}
        return {**lookup, 'scoring_analysis': scoring, 'behavior_evidence': evidence['behavior'],
                'graph_evidence': self.graph_summary(lookup['address_id'])}
