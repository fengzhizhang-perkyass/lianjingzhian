"""Export honest tracing tradeoffs, paired descriptive intervals and figures."""
import _bootstrap
import argparse
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from src.utils.io import ROOT,read_json,save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',default='tracing_v2_release_stable')
    parser.add_argument('--bootstrap-samples',type=int,default=2000)
    args = parser.parse_args()
    from src.utils.io import artifact_key
    if artifact_key(args.experiment) != args.experiment: raise ValueError('Unsafe experiment name')
    folder = ROOT/'artifacts/experiments'/args.experiment
    config = read_json(folder/'protocol.json')['config']
    evaluation = read_json(folder/'evaluation_results.json')
    selection = read_json(folder/'selection.json')
    assert selection['tracing_revision'] == evaluation['tracing_revision']
    frame = pd.DataFrame(evaluation['rows'])
    summary = pd.DataFrame(evaluation['summary']).set_index('method')
    method = selection['method']
    chosen = frame[frame.method == method].set_index('address_id')
    rng = np.random.default_rng(config['seed'])
    paired = []
    for baseline in ('budget_beam','lower_threshold_beam','zero_beam_anchor_filter','bfs_anchor_filter','bridge3_coverage'):
        original = frame[frame.method == baseline].set_index('address_id').loc[chosen.index]
        for metric in ('risk_anchor_nodes','unique_edges','known_illicit_hits','edge_inspections'):
            delta = (chosen[metric]-original[metric]).to_numpy()
            estimates = np.zeros(args.bootstrap_samples)
            # Preserve the intentional risk/category strata. This is a descriptive
            # interval for the sampled protocol, not a whole-population guarantee.
            strata = chosen.groupby(['risk_band','category']).indices
            for ids in strata.values():
                estimates += delta[ids][rng.integers(0,len(ids),size=(args.bootstrap_samples,len(ids)))].sum(axis=1)/len(delta)
            paired.append({'baseline':baseline,'metric':metric,'mean_paired_delta':float(delta.mean()),
                'stratified_bootstrap_95pct_interval':np.quantile(estimates,[.025,.975]).tolist(),
                'positive_seed_count':int((delta > 0).sum()),'negative_seed_count':int((delta < 0).sum())})
    construction = evaluation['anchor_index_construction']
    reduction = summary.loc['bridge3_coverage','mean_edge_inspections']-summary.loc[method,'mean_edge_inspections']
    output = {'selected_profile':method,'seed_count':len(chosen),'paired_descriptive_intervals':paired,
        'bootstrap_samples':args.bootstrap_samples,'bootstrap_seed':config['seed'],
        'offline_index_construction':construction,
        'edge_read_break_even_queries_vs_online_bridge':math.ceil(construction['construction_edge_inspections']/reduction) if reduction > 0 else None,
        'break_even_definition':'edge reads only, against online bridge3 coverage; excludes load time and hardware variability',
        'counts_are_summed_per_seed_not_globally_deduplicated':True}
    save_json(folder/'comparison_analysis.json',output)
    figures = folder/'figures'
    figures.mkdir(exist_ok=True)
    methods = ['budget_beam',method,'zero_beam_anchor_filter','bfs_anchor_filter']
    labels = ['Original\nbeam','Anchor\nwitness','Open beam\n+ anchor filter','Bounded BFS\n+ anchor filter']
    colors = ['#718096','#2563eb','#d97706','#7c3aed']
    fig,axes = plt.subplots(1,3,figsize=(13,4.7))
    for ax,metric,title in zip(axes,['mean_risk_anchor_nodes','mean_edge_inspections','latency_p95_ms'],
        ['Returned risk anchors per seed','Online relation inspections per seed','Warm search latency p95 (ms)']):
        values = [summary.loc[m,metric] for m in methods]
        ax.bar(range(len(methods)),values,color=colors)
        ax.set_xticks(range(len(methods)),labels,fontsize=8.5)
        ax.set_title(title,fontsize=11,pad=16)
        if metric != 'mean_risk_anchor_nodes': ax.set_yscale('log')
        ax.set_ylim(top=max(values)*(2.2 if metric != 'mean_risk_anchor_nodes' else 1.3))
        for i,value in enumerate(values): ax.text(i,value*1.06,f'{value:.3g}',ha='center',fontsize=9)
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Frozen 72-seed relation tracing evaluation',fontsize=14)
    fig.text(.5,.015,'Stratified sample; risk >= 30 defines an anchor, not money-flow truth. Offline index build reported separately.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.08,1,.93])
    fig.savefig(figures/'tracing_tradeoffs.png',dpi=180)
    fig.savefig(figures/'tracing_tradeoffs.svg')
    plt.close(fig)
    lines = ['# 模块二冻结实验结果','',
        f'选择方案：`{method}`。开发 36 个 Seed，评估 72 个 Seed；19 个对照/消融。',
        '每个方法在线上限 2,000 次关系检查；实际开销不同。离线索引成本另列。',
        '指标都是本样本的关系检索指标，不是真实洗钱资金链准确率。unknown 不作为正常标签。','',
        '| 方法 | 风险锚点/Seed | 唯一边/Seed | 已知 illicit 命中/Seed | 在线检查/Seed | p95 ms |',
        '|---|---:|---:|---:|---:|---:|']
    for name in summary.index:
        row=summary.loc[name]
        lines.append(f"| {name} | {row.mean_risk_anchor_nodes:.4f} | {row.mean_unique_edges:.4f} | {row.mean_known_illicit_hits:.4f} | {row.mean_edge_inspections:.2f} | {row.latency_p95_ms:.4f} |")
    lines += ['',f"索引构建：{construction['construction_edge_inspections']:,} 次逆向关系读取，{construction['construction_seconds']:.3f} 秒。",
        f"与在线三节点桥接相比，按关系读取数计算的摊销平衡约为 {output['edge_read_break_even_queries_vs_online_bridge']:,} 次查询；不能将温启动耗时冒充全流程耗时。",'',
        '旧 Beam 返回的风险锚点、唯一边和已知 illicit 命中较少；新方案提升覆盖并保留完整见证。',
        '更宽松 Beam / BFS 在部分覆盖指标上更强；新方案更强调在线检查成本和可核查连接。',
        'PPR 在此样本未增加覆盖，不进入当前默认方案。多样性主要改善构造分支恢复与前缀展示，不能宣称真实图全面显著提升。','',
        '![追踪覆盖与开销](figures/tracing_tradeoffs.png)','',
        '原始数据：[evaluation_rows.csv](evaluation_rows.csv)；配对区间：[comparison_analysis.json](comparison_analysis.json)；冻结选择：[selection.json](selection.json)。']
    (folder/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Summary:',folder/'REPORT.md')


if __name__ == '__main__':
    main()
