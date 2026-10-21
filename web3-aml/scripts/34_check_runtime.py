"""Verify the handoff bundle and exercise real inference with no external LLM calls."""
import _bootstrap
import argparse
import json
import sys
from src.utils.io import ROOT,read_json,file_sha256,save_json


def check(check_ui=False):
    manifest=read_json(ROOT/'runtime_manifest.json')
    missing=[];changed=[]
    for item in [*manifest['files'],*manifest['required_processed_files']]:
        path=ROOT/item['path']
        if not path.is_file():missing.append(item['path'])
        elif file_sha256(path)!=item['sha256']:changed.append(item['path'])
    if missing or changed:
        print(json.dumps({'missing':missing,'changed':changed},ensure_ascii=False,indent=2))
        raise SystemExit('Missing or mismatched files. Place the supplied processed directory at data/processed, and use matching code/artifacts.')
    # Fail if the runtime unexpectedly imports the legacy training stack.
    class BlockTrainingImports:
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] in {'torch','torch_geometric','captum'}:
                raise ImportError('Current frontend runtime must not require '+fullname)
    sys.meta_path.insert(0,BlockTrainingImports())
    from src.inference.analysis_service import AnalysisService
    from src.report.audited_reporter import AuditedReportGenerator
    service=AnalysisService()
    assert service.metadata['fingerprint']==manifest['dataset_fingerprint']
    assert service.metadata['risk_revision']==manifest['risk_revision']
    cases=read_json(ROOT/'artifacts/demo_cases.json')
    summaries=[]
    for group,addresses in cases.items():
        for address in addresses:
            analysis=service.analyze(address)
            assert abs(analysis['scoring_analysis']['additivity_residual'])<1e-5
            trace=service.trace(address)
            for path in trace['top_paths']:
                assert len(path['nodes'])==len(set(path['nodes']))
                assert all(dst in service.graph.out_neighbors(src) for src,dst in zip(path['nodes'],path['nodes'][1:]))
            evidence=service.evidence(analysis,trace)
            report=AuditedReportGenerator(ROOT,config={'enabled':False}).generate(evidence,graph=service.graph,risk_scores=service.risks)
            assert report['source']=='template' and address in report['markdown']
            summaries.append({'group':group,'address':address,'risk':analysis['risk']['overall_score'],
                              'paths':len(trace['top_paths']),'statements':report['audit']['final_statement_count']})
    long=read_json(ROOT/service.tracer.config['long_path_cases'])['cases'][0]
    trace=service.trace(long['address_id'],service.tracer.config['long_path_profile'])
    assert max((p['hop_count'] for p in trace['top_paths']),default=0)==long['hops']==32
    pages=[]
    if check_ui:
        # Local verification only. Do not read credentials or call the live API.
        from unittest.mock import patch
        import src.report.audited_reporter as reporter
        real_load=reporter.load_config
        def offline_load(name,*args,**kwargs):
            config=real_load(name,*args,**kwargs)
            if name=='llm.yaml':config['llm']['enabled']=False
            return config
        from streamlit.testing.v1 import AppTest
        with patch.object(reporter,'load_config',side_effect=offline_load),patch.object(reporter,'load_dotenv',return_value=False):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=120).run()
            assert not app.exception,str(app.exception)
            for page in ['系统总览','调查优先队列','地址风险分析','关系链追踪','AI 分析报告','模型评估']:
                app.radio(key='page').set_value(page).run()
                assert not app.exception,str(app.exception)
                if page=='关系链追踪':
                    app.button(key='FormSubmitter:trace_parameters-运行关系链追踪').click().run()
                    assert not app.exception,str(app.exception)
                if page=='AI 分析报告':
                    next(b for b in app.button if b.label=='生成 AML 分析报告').click().run()
                    assert not app.exception,str(app.exception)
                    assert any('Web3 AML 风险分析报告' in e.value for e in app.markdown)
                pages.append(page)
    result={'status':'passed','addresses':len(service.risks),'cases':summaries,
            'longest_demo_hops':32,'pages_checked':pages,'live_llm_tested':False,
            'training_stack_required':False,'raw_csv_present':(ROOT/'data/raw/wallets_features.csv').exists()}
    save_json(ROOT/'artifacts/metrics/runtime_handoff_check.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui',action='store_true',help='Also exercise every Streamlit page with the template reporter.')
    check(parser.parse_args().ui)
