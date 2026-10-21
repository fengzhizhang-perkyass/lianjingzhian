"""Web report execution limits and safe diagnostics over the original protocol."""
import os
from src.report.audited_reporter import AuditedReportGenerator
from src.report.report_audit import save_bundle
from src.utils.io import artifact_key, save_json


def failure_code(exc):
    if isinstance(exc, ValueError) and str(exc) == 'Model output truncated by token limit':
        return 'output_truncated'
    return {
        'APITimeoutError': 'timeout', 'TimeoutError': 'timeout',
        'APIConnectionError': 'connection', 'AuthenticationError': 'authentication',
        'PermissionDeniedError': 'permission', 'RateLimitError': 'rate_limit',
        'BadRequestError': 'invalid_request', 'InternalServerError': 'provider_error',
    }.get(type(exc).__name__, 'request_failed')


MESSAGES = {
    'output_truncated': 'LLM回答达到输出长度上限，内容被截断，本次使用源证据声明模板。',
    'timeout': 'LLM响应超时，本次使用源证据声明模板；可稍后重新生成。',
    'connection': '暂时无法连接LLM服务，本次使用源证据声明模板；可稍后重新生成。',
    'authentication': 'LLM密钥验证失败，本次使用源证据声明模板，请检查服务端配置。',
    'permission': 'LLM接口权限不足，本次使用源证据声明模板，请检查模型权限。',
    'rate_limit': 'LLM服务触发限流或用量限制，本次使用源证据声明模板；可稍后重试。',
    'invalid_request': 'LLM接口未接受本次请求参数，本次使用源证据声明模板。',
    'provider_error': 'LLM服务暂时异常，本次使用源证据声明模板；可稍后重新生成。',
    'request_failed': 'LLM本次请求未完成，已使用源证据声明模板。',
}


class WebReportGenerator(AuditedReportGenerator):
    def __init__(self, *args, **kwargs):
        explicit_config = kwargs.get('config') is not None
        super().__init__(*args, **kwargs)
        self.config = dict(self.config)
        if not explicit_config:
            # Optional facts can make valid structured reports exceed the old 8K cap.
            self.config['max_tokens'] = int(os.environ.get('LLM_MAX_TOKENS', '32768'))
            self.config['timeout'] = int(os.environ.get('LLM_TIMEOUT_SECONDS', '90'))
        if not 1 <= self.config.get('max_tokens', 32768) <= 65536:
            raise ValueError('LLM_MAX_TOKENS must be between 1 and 65536')
        if not 1 <= self.config.get('timeout', 90) <= 90:
            raise ValueError('LLM_TIMEOUT_SECONDS must be between 1 and 90')
        # Save once, after diagnostics are added, keeping disk and download hashes consistent.
        self.persist = self.reporting['persist_audit']
        self.reporting['persist_audit'] = False
        self.request_failures = []

    def _request(self, messages):
        try:
            return super()._request(messages)
        except Exception as exc:
            self.request_failures.append({'code': failure_code(exc), 'error_type': type(exc).__name__})
            raise

    def generate(self, evidence, graph=None, risk_scores=None):
        self.request_failures = []
        report = super().generate(evidence, graph=graph, risk_scores=risk_scores)
        report['audit']['request_failures'] = list(self.request_failures)
        report['audit']['generation_limits'] = {k: self.config.get(k) for k in ('max_tokens', 'timeout', 'max_retries')}
        if report['source'] == 'template':
            if self.request_failures:
                report['fallback_reason'] = MESSAGES[self.request_failures[0]['code']]
            elif any(c['stage'] == 'generation_failure' for c in report['candidates']):
                report['fallback_reason'] = 'LLM返回内容未满足报告格式要求，本次使用源证据声明模板。'
        if self.persist:
            report['bundle_path'] = save_bundle(self.root, report)
        return report


def generate_web_report(service, evidence):
    report = WebReportGenerator(service.root).generate(evidence, graph=service.graph, risk_scores=service.risks)
    # Preserve legacy latest-by-address files alongside the immutable API snapshots.
    key = artifact_key(evidence['target']['address_id'])
    save_json(service.root / 'artifacts/reports' / f'{key}_evidence.json', evidence)
    (service.root / 'artifacts/reports' / f'{key}.md').write_text(report['markdown'], encoding='utf-8')
    return report
