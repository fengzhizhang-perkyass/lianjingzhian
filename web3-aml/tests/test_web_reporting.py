import json
from types import SimpleNamespace
import httpx
import pytest
from openai import APITimeoutError, AuthenticationError
from api.reporting import WebReportGenerator
from src.report.evidence_builder import build_evidence
from src.report.fact_catalog import FactCatalog
from src.report.claim_schema import empty_document, blueprint
from src.utils.io import load_config, file_sha256


@pytest.fixture
def report_inputs():
    evidence = build_evidence(
        {'address_id': 'A', 'risk': {'overall_score': 40, 'risk_level': 'MEDIUM'}},
        behavior_evidence=[], graph_evidence={},
        trace_result={'seed_address': 'A', 'config': {}, 'top_paths': []},
        metadata={'risk_revision': 'fixture', 'fingerprint': 'fixture'})
    settings = {**load_config('reporting.yaml'), 'persist_audit': True}
    catalog = FactCatalog(evidence, settings)
    document = empty_document()
    for section in document['sections']:
        section['claims'] = [blueprint(f) for f in catalog.facts.values() if f['section'] == section['section']]
    return evidence, settings, document


def generator(tmp_path, settings, responses):
    replies = iter(responses)
    def create(**kwargs):
        item = next(replies)
        if isinstance(item, Exception):
            raise item
        reason, content = item
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason,
            message=SimpleNamespace(content=content if isinstance(content, str) else json.dumps(content)))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return WebReportGenerator(tmp_path, config={'enabled': True, 'base_url': 'https://invalid.example',
        'api_key': 'fixture-secret', 'model': 'fixture', 'temperature': .2, 'timeout': 1,
        'max_tokens': 8192, 'max_retries': 0}, client=client, reporting_config=settings)


def test_truncation_then_success_does_not_reuse_fallback(tmp_path, report_inputs):
    evidence, settings, document = report_inputs
    reporter = generator(tmp_path, settings, [('length', '{'), ('stop', document)])
    failed = reporter.generate(evidence)
    assert failed['source'] == 'template'
    assert '被截断' in failed['fallback_reason']
    assert failed['audit']['request_failures'][0]['code'] == 'output_truncated'
    success = reporter.generate(evidence)
    assert success['source'] == 'llm'
    assert success['fallback_reason'] is None
    assert success['audit']['request_failures'] == []
    assert success['report_id'] != failed['report_id']
    assert success['audit']['unresolved_final_claims'] == 0
    for report in [failed, success]:
        folder = tmp_path/'artifacts/reports'/report['report_id']
        manifest = json.loads((folder/'manifest.json').read_text())
        assert json.loads((folder/'audit.json').read_text()) == report['audit']
        assert all(file_sha256(folder/name) == sha for name, sha in manifest['file_sha256'].items())


def test_malformed_json_has_format_failure_not_key_failure(tmp_path, report_inputs):
    evidence, settings, _ = report_inputs
    report = generator(tmp_path, settings, [('stop', '{bad json')]).generate(evidence)
    assert report['source'] == 'template'
    assert '格式要求' in report['fallback_reason']
    assert report['audit']['request_failures'] == []


@pytest.mark.parametrize('exc,code', [
    (APITimeoutError(request=httpx.Request('POST', 'https://invalid.example')), 'timeout'),
    (AuthenticationError('fixture-secret', response=httpx.Response(401, request=httpx.Request('POST', 'https://invalid.example')), body=None), 'authentication'),
])
def test_safe_specific_error_diagnostics(tmp_path, report_inputs, exc, code):
    evidence, settings, _ = report_inputs
    report = generator(tmp_path, settings, [exc]).generate(evidence)
    assert report['audit']['request_failures'][0]['code'] == code
    assert 'fixture-secret' not in json.dumps(report, ensure_ascii=False)


def test_web_default_output_limit_is_32k(monkeypatch):
    monkeypatch.delenv('LLM_MAX_TOKENS', raising=False)
    monkeypatch.delenv('LLM_TIMEOUT_SECONDS', raising=False)
    reporter = WebReportGenerator()
    assert reporter.config['max_tokens'] == 32768
    assert reporter.config['timeout'] == 90
    assert reporter.config['max_retries'] == 0
