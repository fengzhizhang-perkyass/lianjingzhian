"""Install validated long-range examples while preserving the quick default."""
import _bootstrap
from pathlib import Path
import shutil
from src.utils.io import ROOT, read_json, load_config, save_json
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.graph_loader import DirectedGraph


def main():
    source = ROOT/'artifacts/experiments/tracing_long_paths_v2'
    results = read_json(source/'results.json')
    active = read_json(ROOT/'artifacts/risk_scores/metadata.json')
    assert all(results['provenance'][k] == active[k] for k in results['provenance'])
    config = load_config('tracing.yaml')
    target = ROOT/config['anchor_index_path']
    target.mkdir(parents=True, exist_ok=True)
    for name in ('metadata.json','distance.npy','next_node.npy'):
        if not (target/name).exists():
            shutil.copyfile(source/'anchor_index'/name, target/name)
    graph = DirectedGraph.load()
    RiskAnchorIndex.load(graph, target, results['provenance'], config['risk_threshold'],
                         config['long_path_profile']['max_depth'])
    traces = read_json(source/'selected_demo_traces.json')
    cases = []
    for sample in traces:
        if sample['method'] != 'long_connectors32':
            continue
        path = max(sample['result']['top_paths'], key=lambda p: p['hop_count'])
        cases.append({'address_id': sample['seed']['address_id'], 'hops': path['hop_count'],
            'seed_score': path['node_risks'][0], 'endpoint_score': path['node_risks'][-1],
            'sampling': sample['seed']['split'], 'evidence_id': path['evidence_id']})
    cases.sort(key=lambda c: (-c['hops'], c['address_id']))
    save_json(ROOT/config['long_path_cases'], {'provenance': results['provenance'],
        'tracing_revision': results['tracing_revision'], 'profile': config['long_path_profile'],
        'selection_bias': 'long examples deliberately selected; not representative performance', 'cases': cases})
    summaries = [r for r in results['summary'] if r['split'] == 'evaluation']
    table = ['|方法|非空起点 / 72|最长路径|关系边累计|锚点累计|平均在线检查|',
             '|---|---:|---:|---:|---:|---:|']
    for r in summaries:
        table.append(f"|{r['method']}|{r['nonempty']}|{r['max_hops']}|{r['sum_unique_edges']}|{r['sum_anchors']}|{r['mean_checks']:.2f}|")
    text = '# 长链关联核查实验（2026-10-12）\n\n'
    text += ('在既有36开发/72评估起点上进行探索性复测，样本此前已观察，不能作为新的盲测。'
             '模块一评分未修改。六个配置在运行前保存，不依据标签搜索。\n\n')
    text += '\n'.join(table)+'\n\n'
    text += ('仅提高深度可在原72个起点中找到11跳路径，但非空起点仍17个。允许更长完整连接段后，'
             '非空起点19个；没有普遍产生长链，72个起点中只有1个返回至少8跳路径。'
             '以上均为逐起点去重累计，不是全局唯一量或洗钱路径召回率。\n\n')
    text += ('另按最短锚点距离选了3个展示起点：距离32跳，每个返回33个不同地址的真实有向路径，'
             '在线检查33次。原4跳配置均没有结果。它们起点风险约1.77、终点41.20–49.44，'
             '证明远距离关系核查能力，不证明洗钱或连续资金转移。展示起点有选择偏差，不进入72样本指标。\n\n')
    text += ('离线64跳索引成本独立记录在graph_diagnostics.json；默认仍4跳、最多3个连续低分节点。'
             '长链模式为32跳、最多31个连续低分节点，深度与低分跨度同时放宽，关系噪声可能增大。'
             '单canonical最短见证不保证找到所有路径。\n\n')
    text += '## 可复现产物\n\n- [逐起点结果](rows.csv)\n- [来源和全图距离分布](graph_diagnostics.json)\n- [完整路径JSON](selected_demo_traces.json)\n- [运行前协议](protocol.json)\n'
    (source/'REPORT.md').write_text(text, encoding='utf-8')
    print('Installed validated index and', len(cases), 'long-path examples. Quick default unchanged.')


if __name__ == '__main__':
    main()
