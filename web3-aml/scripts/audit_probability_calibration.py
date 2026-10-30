"""Audit existing frozen split roles without opening label arrays or fitting.

This records qualification/shortage and score distributions. It never fabricates
a reliability curve from training labels or uses the final test for selection.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.probability_calibration import model_signature
from src.utils.io import read_json, save_json, file_sha256


def distribution(folder):
    frame = pd.read_parquet(folder/'risk_scores.parquet', columns=['overall_risk_score'])
    scores = frame.overall_risk_score.to_numpy()
    bins = [0, 30, 60, 80, 90, 99, 99.995, 100]
    counts, _ = np.histogram(scores, bins=bins)
    return {'label_blind': True, 'rows': len(scores), 'maximum_score': float(scores.max()),
            'minimum_score': float(scores.min()),
            'exact_100_count': int((scores == 100).sum()),
            'rounded_100_but_not_exact': int(((scores >= 99.995) & (scores < 100)).sum()),
            'bins': [{'lower': lo, 'upper': hi, 'count': int(n)}
                     for lo, hi, n in zip(bins[:-1], bins[1:], counts)],
            'interpretation': 'Score distribution only; does not establish probability calibration'}


def audit_bitcoin(root):
    data = root/'data/processed'
    run = root/'model_upgrade/remote_records/entity_refit/model_upgrade/all_pretest_refit/runs/fixed_s42'
    masks = {k: np.load(data/(k+'_mask.npy'), allow_pickle=False) for k in ('train', 'val', 'test')}
    fitted = np.load(run/'all_pretest_mask.npy', allow_pickle=False)
    assert all(v.dtype == bool and v.shape == fitted.shape for v in masks.values())
    assert np.array_equal(fitted, masks['train'] | masks['val'])
    assert not np.any(fitted & masks['test'])
    metadata = read_json(data/'metadata.json')
    record = read_json(run/'manifest.json')
    assert int(fitted.sum()) == record['training_nodes'] == 208918
    return {
        'training_mask_equals_original_train_union_validation': True,
        'fitted_rows': int(fitted.sum()), 'fitted_time_range': record['training_time_range'],
        'roles': [
            {'name': 'original_train', 'rows': int(masks['train'].sum()), 'positives_from_metadata': metadata['split']['train']['illicit'],
             'base_training': True, 'calibration_fit_eligible': False, 'independent_check_eligible': False},
            {'name': 'original_validation', 'rows': int(masks['val'].sum()), 'positives_from_metadata': metadata['split']['val']['illicit'],
             'base_training': True, 'calibration_fit_eligible': False, 'independent_check_eligible': False},
            {'name': 'original_test', 'rows': int(masks['test'].sum()),
             'role': 'fixed_final_evaluation_only', 'calibration_fit_eligible': False, 'independent_selection_eligible': False}],
        'remaining_rows': {'count': int((~(fitted | masks['test'])).sum()),
                           'role': 'Outside original known-label development/test masks; not assumed benign or independently labeled'},
        'shortage': ['No verified non-training labeled fitting cohort outside the fixed test in the supplied release',
                     'No separately qualified independent calibration-check cohort'],
        'evidence_files': [str((run/'manifest.json').relative_to(root)), str((run/'all_pretest_mask.npy').relative_to(root)),
                           *[str((data/(k+'_mask.npy')).relative_to(root)) for k in masks],
                           'data/processed/metadata.json']}


def audit_ethereum(root):
    folder = root/'data/external/ethereum/processed'
    metadata = read_json(folder/'metadata.json')
    # npz members are lazy: only split and addresses are opened, never X/y/tokens.
    with np.load(folder/'dataset.npz', allow_pickle=False) as data:
        split = data['split']
        addresses = data['addresses']
        assert set(split.tolist()) == {0, 1, 2} and len(np.unique(addresses)) == len(addresses)
        counts = [int((split == k).sum()) for k in (0, 1, 2)]
    assert counts == [metadata['split'][k]['n'] for k in ('train', 'validation', 'test')]
    selection = read_json(root/'model_upgrade/ethereum/artifacts/selection.json')
    assert selection['selection_metric'] == 'validation_average_precision'
    return {'address_disjoint_original_split': True, 'split_protocol': metadata['split_protocol'],
        'roles': [
            {'name': 'original_train', 'rows': counts[0], 'positives_from_metadata': metadata['split']['train']['positive'],
             'base_training': True, 'calibration_fit_eligible': False, 'independent_check_eligible': False},
            {'name': 'original_validation', 'rows': counts[1], 'positives_from_metadata': metadata['split']['validation']['positive'],
             'used_for': ['tree_early_stopping', 'encoder_checkpoint_selection', 'fusion_model_selection', 'threshold_selection'],
             'gradient_training_cohort': False,
             'calibration_fit_candidate_requires_new_protocol': True, 'independent_check_eligible': False},
            {'name': 'original_test', 'rows': counts[2], 'role': 'fixed_final_evaluation_only',
             'calibration_fit_eligible': False, 'independent_selection_eligible': False}],
        'label_scope': 'Provided phishing/malicious centers versus background-negative addresses; not a full-chain AML prevalence estimate',
        'shortage': ['Validation was already used for early stopping and selection; cannot certify same-cohort fitting and checking as independent',
                     'No separately qualified independent calibration-check cohort in the supplied release'],
        'evidence_files': ['data/external/ethereum/processed/metadata.json',
                           'model_upgrade/ethereum/train_baselines.py', 'model_upgrade/ethereum/train_igt4eth.py',
                           'model_upgrade/ethereum/select_and_evaluate.py', 'model_upgrade/ethereum/artifacts/selection.json']}


def main():
    summary = []
    for dataset_id, audit in [('bitcoin', audit_bitcoin), ('ethereum', audit_ethereum)]:
        frozen = ROOT/'artifacts/datasets'/dataset_id/'current'
        manifest = read_json(frozen/'manifest.json')
        details = audit(ROOT)
        details.update(dataset_id=dataset_id, status='needs_data',
                       label_arrays_opened=False, labels_used_for_fit=False,
                       test_labels_loaded=False, base_models_trained=False,
                       original_splits_modified=False, calibration_fit_performed=False,
                       reliability_conclusion='not_established_without_qualified_independent_data',
                       score_distribution=distribution(frozen))
        details['source_sha256'] = {p: file_sha256(ROOT/p) for p in details['evidence_files']}
        target = ROOT/'artifacts/calibration'/dataset_id/'current'
        target.mkdir(parents=True, exist_ok=True)
        save_json(target/'audit.json', details)
        release = {'dataset_id': dataset_id, 'model_signature': model_signature(dataset_id, manifest),
                   'mode': 'identity', 'status': 'needs_data', 'parameters': {},
                   'audit_sha256': file_sha256(target/'audit.json')}
        save_json(target/'manifest.json', release)
        summary.append({'dataset_id': dataset_id, 'status': 'needs_data', 'shortage': details['shortage'],
                        'score_distribution': details['score_distribution']})
    save_json(ROOT/'artifacts/v31_checks/calibration_audit.json', {'datasets': summary, 'base_models_trained': False})
    report = ['# 双数据集概率校准数据审计', '',
              '本次仅核对既有划分用途并统计无标签分数分布。未训练模型、未拟合校准器、未打开测试标签数组。', '',
              '## 结论', '',
              '- 比特币：冻结B3训练掩码与原训练集和验证集的并集完全相同（208,918条）。原验证期不能作为其独立校准数据。',
              '- 以太坊：原验证集15,476条、483个正类，已用于早停、编码器选择、融合选型和阈值选择；另无已核验的独立校准检验集。',
              '- 两条链记录为needs_data，当前映射保持identity，不宣称已通过概率可靠性检查。', '',
              '## 后续数据方案', '',
              '1. 优先补充未参与现有训练或选型、特征可由冻结流程计算的真实带标签地址，并核验来源、分布与地址重叠。',
              '2. 先约定独立拟合与检验用途，保持原测试集不变，不用测试标签拟合或选校准参数。',
              '3. 数据到位后检查可靠性曲线、分箱实际比例及不确定性，再判断是否需要校准；目前不能只凭接近满分数量断言失真。',
              '4. 未获得新的决定前，不重新划分、不重训、不自动把旧验证集拆成新的校准集，不临时乘系数压分。', '',
              '## 当前无标签分数分布', '']
    for row in summary:
        d = row['score_distribution']
        report.append(f"- {row['dataset_id']}：{d['rows']}条，最高{d['maximum_score']!r}；真实100分{d['exact_100_count']}条，因两位小数显示成100的不足满分值{d['rounded_100_but_not_exact']}条。")
    report.extend(['', '这份直方统计不使用实际标签，因此不是可靠性曲线，不证明分数已经校准。', '',
                   '详细数据用途与来源散列见artifacts/calibration/{bitcoin,ethereum}/current/audit.json。'])
    (ROOT/'artifacts/v31_checks/概率校准数据审计.md').write_text('\n'.join(report)+'\n')
    print(json.dumps({'status': 'needs_data', 'datasets': [r['dataset_id'] for r in summary],
                      'label_arrays_opened': False, 'calibration_fit_performed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
