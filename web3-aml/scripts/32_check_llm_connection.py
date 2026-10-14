"""One small real API probe; --report additionally checks one real AML Evidence case.

Never prints credentials or raw exception messages. Template fallback is not success.
"""
import _bootstrap
import argparse
import json
from urllib.parse import urlparse
from openai import AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError
from src.report.llm_reporter import LLMReporter
from src.utils.io import ROOT,read_json,save_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',action='store_true',help='Also send one real public-data AML Evidence case')
    args=parser.parse_args()
    reporter=LLMReporter(ROOT)
    cfg=reporter.config
    if not all(cfg.get(k) for k in ('base_url','api_key','model')):
        print('尚未配置完整连接信息：请在项目.env内填写LLM_API_KEY。不会显示密钥。')
        return 2
    original_limit=cfg.get('max_tokens')
    cfg['max_tokens']=128
    try:
        raw,usage=reporter._request([{'role':'system','content':'Return only JSON: {"ok":true}.'},
            {'role':'user','content':'Test JSON output. Return {"ok":true}.'}])
        if json.loads(raw)!={'ok':True}:raise ValueError('Probe response does not match expected JSON')
    except AuthenticationError:
        print('认证失败：请核对本地Key是否属于当前API服务。');return 3
    except RateLimitError:
        print('额度或限流错误：请查看服务商控制台余额和请求限制。');return 3
    except (APIConnectionError,APITimeoutError):
        print('连接失败或超时：请检查网络及LLM_BASE_URL。');return 3
    except APIStatusError as exc:
        print(f'服务端拒绝请求，HTTP状态码：{exc.status_code}。请核对模型名和参数。');return 3
    except Exception as exc:
        print('响应核验未通过，错误类型：'+type(exc).__name__);return 3
    finally:
        if original_limit is None:cfg.pop('max_tokens',None)
        else:cfg['max_tokens']=original_limit
    result={'connection_passed':True,'endpoint_host':urlparse(cfg['base_url']).hostname,
        'requested_model':cfg['model'],'provider':cfg.get('provider'),'thinking_mode':cfg.get('thinking_mode'),
        'probe_usage':usage,'live_report_tested':False}
    if args.report:
        from src.inference.analysis_service import AnalysisService
        service=AnalysisService()
        address=read_json(ROOT/'artifacts/demo_cases.json')['high_risk_unknown'][0]
        trace=service.trace(address)
        evidence=service.evidence(service.analyze(address),trace)
        report=reporter.generate(evidence,graph=service.graph,risk_scores=service.risks)
        audit=report['audit']
        result.update(live_report_tested=True,report_id=report['report_id'],report_source=report['source'],
            initial_passed=audit['initial_passed_count'],repaired=audit['repaired_count'],
            coverage_added=audit['coverage_added_count'],api_calls=audit['api_calls'],
            candidate_errors=audit['candidate_error_count'],bundle_path=report.get('bundle_path'),
            elapsed_ms=audit['elapsed_ms'],reporting_revision=audit['reporting_revision'],
            llm_report_passed=report['source']=='llm' and audit['unresolved_final_claims']==0,
            fallback_used=report['source']!='llm' or audit['local_fallback_count']>0)
    save_json(ROOT/'artifacts/metrics/llm_connection_acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if not args.report or result['llm_report_passed'] else 4


if __name__=='__main__':raise SystemExit(main())
