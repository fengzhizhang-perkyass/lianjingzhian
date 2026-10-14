"""Write compact, reproducible results and a publication-style comparison figure."""
import _bootstrap
from pathlib import Path
import numpy as np
import pandas as pd
from src.utils.io import ROOT, read_json, save_json

folder = ROOT / 'artifacts/experiments/evidence_tree_v1'
final = read_json(folder / 'final_summary.json')
seed, recipe, parameter = final['representative_seed'], final['selection']['recipe'], final['matched_parameter']
selected = folder / f'final/seed_{seed}/{recipe}__{parameter}'
result = read_json(selected / 'test.json')
reference = pd.read_csv(ROOT / 'artifacts/experiments/roles_v1/final_comparison.csv')
matched = pd.read_csv(folder / 'final_comparison.csv')
removals = pd.read_csv(ROOT / 'artifacts/experiments/evidence_tree_v1_ablation/comparison.csv')
means = reference.groupby('candidate')[['pr_auc', 'f1', 'recall']].mean()
summary = {'current_model': '有向邻域对比证据融合', 'seed': seed,
           'test': {k: result[k] for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc', 'brier_score', 'threshold', 'review']},
           'ap_gain_vs_graphsage_mean': result['pr_auc']-float(means.loc['graphsage', 'pr_auc']),
           'ap_gain_vs_old_redundant_mean': result['pr_auc']-float(means.loc['old_redundant', 'pr_auc']),
           'removals': removals.to_dict(orient='records'),
           'selection': final['selection'], 'test_already_observed': True,
           'deterministic_tree': True, 'three_seeds_are_not_independent_replications': True}
save_json(folder / 'findings.json', summary)
comparison_rows = [{'candidate': n, 'pr_auc': float(means.loc[n, 'pr_auc']), 'f1': float(means.loc[n, 'f1']),
                    'recall': float(means.loc[n, 'recall']), 'scope': 'three neural seeds mean'}
                   for n in ['behavior', 'graphsage', 'dual_view', 'old_redundant']]
comparison_rows.append({'candidate': 'evidence_fusion', **{k: result[k] for k in ['pr_auc', 'f1', 'recall']}, 'scope': 'one deterministic tree result'})
pd.DataFrame(comparison_rows).to_csv(folder / 'historical_comparison.csv', index=False)
lines = ['# 当前主模型：有向邻域对比证据融合', '',
         '输入：51 项地址行为、102 项上游 / 下游标准化偏离、18 项有向结构，共 171 项。',
         '联合 LightGBM 融合特征；单类模型只用于诊断，不参与概率平均。当前不使用 GraphSAGE 或 MLP。', '',
         '## 冻结选择', '',
         f'- 配方 `{recipe}`，预算 `{parameter}`，代表种子 {seed}。',
         '- 三段验证 AP 的权重为 0.2 / 0.2 / 0.6，最近验证时间段占主要权重；选择前写入配置。',
         '- 树的早停、校准、阈值选择均使用验证标签；测试不参与本轮配方和参数选择。',
         '- 测试集此前已被其他版本查看，本轮仍属于重复基准评估。', '',
         '## 测试指标', '', '| AP | F1 | Precision | Recall | ROC-AUC | Brier |', '|---:|---:|---:|---:|---:|---:|',
         '| '+' | '.join(f"{result[k]:.4f}" for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc', 'brier_score'])+' |', '',
         '## 同划分历史对比', '', '| 方法 | AP | F1 | Recall | 汇总口径 |', '|---|---:|---:|---:|---|']
for row in comparison_rows:
    lines.append(f"| {row['candidate']} | {row['pr_auc']:.4f} | {row['f1']:.4f} | {row['recall']:.4f} | {row['scope']} |")
lines += ['', '当前 compact 树没有随机子采样，42 / 43 / 44 的预测相同，不能声称三次独立重复验证。', '',
          '## 严格移除消融', '', '| 方法 | AP | F1 | Recall |', '|---|---:|---:|---:|']
for row in removals.to_dict(orient='records'):
    lines.append(f"| {row['candidate']} | {row['pr_auc']:.4f} | {row['f1']:.4f} | {row['recall']:.4f} |")
lines += ['', '所有移除模型重新训练，使用同一 compact 预算、划分、早停、校准协议和种子。',
          '无方向对照先双向化原边，再重新计算偏离和结构特征；没有重新选择主模型。', '',
          '## 有限复核预算', '', '| 预算 | 命中 | 命中率 | illicit 召回 |', '|---|---:|---:|---:|']
for budget, counts in result['review'].items():
    lines.append(f"| {budget} | {counts['illicit_found']}/{counts['reviewed']} | {counts['precision']:.2%} | {counts['recall']:.2%} |")
lines += ['', '仅覆盖 56,436 个已知标签测试地址，其中 2,548 个 illicit。不能外推到 unknown 人群。', '',
          '## 完整四轮记录', '',
          '- `../roles_v1/`：去掉重复 GraphSAGE、纯结构与共享 Head，100 组开发配置。',
          '- `../graph_signals_v1/`：12 种图信号树配方、132 组单模型或融合配置。',
          '- `../multievidence_v1/`：6 种单线、Gate、拼接训练策略；单线 context 在开发中获选，未证明 Gate 更好。',
          '- 本目录：4 种联合配方 × 3 种树预算，在两个开发段和最近验证段比较；另含匹配单类对照。',
          '- `../evidence_tree_v1_ablation/`：五项冻结后的严格移除与方向消融。', '',
          '各目录保留配置、冻结选择、校准、预测和完整 CSV；未采用的实验不会被删除。', '',
          '设计、文献出处、公式、演示和答辩口径见 `../../../docs/RISK_SCORING_REDESIGN.md`。', '']
(folder / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
names = ['Behavior MLP', 'GraphSAGE', 'Dual-view', 'Old 3-expert', 'Evidence fusion']
for ax, metric in zip(axes[:2], ['pr_auc', 'f1']):
    values = [row[metric] for row in comparison_rows]
    ax.barh(names, values, color=['#94A3B8']*4+['#1E40AF'])
    ax.invert_yaxis(); ax.set_xlim(0, .65); ax.set_title('Average Precision' if metric == 'pr_auc' else 'F1')
    for i, value in enumerate(values):ax.text(value+.008, i, f'{value:.3f}', va='center', fontsize=9)
    ax.grid(axis='x', alpha=.2)
values = [result['pr_auc'], *removals[removals.candidate != 'context_z_only'].pr_auc.tolist()]
names = ['All evidence', 'Remove behavior', 'Remove context', 'Remove structure', 'Remove direction']
axes[2].barh(names, values, color=['#1E40AF']+['#94A3B8']*4)
axes[2].invert_yaxis();axes[2].set_xlim(0, .65);axes[2].set_title('Matched feature removals: AP')
for i, value in enumerate(values):axes[2].text(value+.008, i, f'{value:.3f}', va='center', fontsize=9)
axes[2].grid(axis='x', alpha=.2)
fig.suptitle('Elliptic++ time-split snapshot: directed neighborhood evidence fusion')
fig.text(.5, .02, 'Neural baselines: three-seed means. Current tree: one deterministic result. Repeated benchmark, not external blind validation.', ha='center', fontsize=9)
fig.tight_layout(rect=(0, .06, 1, .95))
fig.savefig(folder / 'comparison.png', dpi=200)
plt.close(fig)
print({k: summary[k] for k in ['ap_gain_vs_graphsage_mean', 'ap_gain_vs_old_redundant_mean']})
