"""Install a frozen tracing recipe; preserves scores and the existing Demo IDs."""
import _bootstrap
import argparse
import shutil
import yaml
from src.utils.io import ROOT,read_json,save_json,file_sha256,artifact_key
from src.tracing.graph_loader import DirectedGraph
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',default='tracing_v2_release_stable')
    parser.add_argument('--freeze',action='store_true',help='Freeze recipe after development and before evaluation')
    parser.add_argument('--profile',default='indexed_bridge3')
    args = parser.parse_args()
    from src.utils.io import artifact_key as safe_name
    if safe_name(args.experiment) != args.experiment:
        raise ValueError('Unsafe experiment name')
    folder = ROOT/'artifacts/experiments'/args.experiment
    if args.freeze:
        if (folder/'evaluation_results.json').exists():
            raise RuntimeError('Cannot select a recipe after evaluation results exist')
        protocol = read_json(folder/'protocol.json')
        dev = read_json(folder/'development_results.json')
        settings = protocol['config']['methods'][args.profile]
        save_json(folder/'selection.json',{'method':args.profile,
            'config':{**protocol['config']['common'],**settings},
            'risk_revision':dev['risk_revision'],
            'dataset_fingerprint':read_json(folder/'seed_manifest.json')['dataset_fingerprint'],
            'tracing_revision':dev['tracing_revision'],
            'development_results_sha256':file_sha256(folder/'development_results.json'),
            'selection_basis':'online cost, explicit risk-anchor witness and auditability; not maximum illicit hits',
            'tradeoffs':'one canonical witness; broader search may cover more; index construction counted separately',
            'evaluation_used_for_selection':False,'frozen_before_evaluation':True})
        print('Recipe frozen before evaluation:',args.profile)
        return
    selection = read_json(folder/'selection.json')
    evaluation = read_json(folder/'evaluation_results.json')
    metadata = read_json(ROOT/'artifacts/risk_scores/metadata.json')
    for field in ('risk_revision','dataset_fingerprint'):
        assert selection[field] == metadata[field]
    assert selection['tracing_revision'] == evaluation['tracing_revision']
    assert selection['development_results_sha256'] == file_sha256(folder/'development_results.json')
    assert selection['frozen_before_evaluation'] and not selection['evaluation_used_for_selection']
    graph = DirectedGraph.load()
    risks = pd.read_parquet(ROOT/'artifacts/risk_scores/risk_scores.parquet',
        columns=['address_id','overall_risk_score']).set_index('address_id').overall_risk_score.to_dict()
    provenance = {k:metadata[k] for k in ('risk_revision','dataset_fingerprint')}
    tracer = BudgetedRelationTracer(graph,risks,selection['config'],provenance=provenance)
    if tracer.revision != selection['tracing_revision']:
        raise RuntimeError('Tracing source changed after evaluation: rerun the protocol')
    # Retain old configuration and nine concrete artifacts before replacing outputs.
    backup = folder/'previous_demo'
    if not (backup/'tracing.yaml').exists():
        backup.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'config/tracing.yaml',backup/'tracing.yaml')
        for address in sum(read_json(ROOT/'artifacts/demo_cases.json').values(),[]):
            key = artifact_key(address)
            for source in [ROOT/'artifacts/traces'/f'{key}.json',
                           ROOT/'artifacts/reports'/f'{key}_evidence.json',
                           ROOT/'artifacts/reports'/f'{key}.md']:
                if source.exists():
                    target = backup/source.relative_to(ROOT)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
    threshold = selection['config']['risk_threshold']
    index_relative = f"artifacts/tracing/anchor_index/risk_{metadata['risk_revision'][:8]}_trace_{tracer.revision[:8]}_t{threshold}"
    index_folder = ROOT/index_relative
    if (index_folder/'metadata.json').exists():
        index = RiskAnchorIndex.load(graph,index_folder,provenance,threshold,8)
    else:
        index = RiskAnchorIndex.build(graph,risks,threshold,8,provenance)
        index.save(index_folder)
    config = {**selection['config'],'method':'budgeted','profile':selection['method'],
        'display_name':'风险锚点约束的预算化证据路径追踪','anchor_index_path':index_relative}
    (ROOT/'config/tracing.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
    from src.inference.analysis_service import AnalysisService
    from src.report.template_reporter import TemplateReporter
    service = AnalysisService()
    cases = read_json(ROOT/'artifacts/demo_cases.json')
    rows = []
    for address in sum(cases.values(),[]):
        analysis = service.analyze(address)
        result = service.trace(address)
        evidence = service.evidence(analysis,result)
        report = TemplateReporter().generate(evidence)
        key = artifact_key(address)
        save_json(ROOT/'artifacts/reports'/f'{key}_analysis.json',analysis)
        save_json(ROOT/'artifacts/reports'/f'{key}_evidence.json',evidence)
        (ROOT/'artifacts/reports'/f'{key}.md').write_text(report['markdown'],encoding='utf-8')
        rows.append({'address_id':address,'paths':len(result['top_paths']),
            'max_depth':result['statistics']['max_reached_depth'],
            'unique_edges':result['selection_analysis']['unique_edges'],
            'bridge_nodes':len({a for p in result['top_paths'] for a in p['bridge_nodes']}),
            'actual_edge_inspections':result['search_budget']['actual_edge_inspections']})
    save_json(ROOT/'artifacts/tracing/deployment.json',{'profile':selection['method'],
        'tracing_revision':tracer.revision,**provenance,'selection_path':str(folder.relative_to(ROOT)/'selection.json'),
        'anchor_index':index.metadata,'demo_cases':rows,'live_llm_tested':False})
    print(rows)


if __name__ == '__main__':
    main()
