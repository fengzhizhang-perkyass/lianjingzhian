from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from src.report.evidence_builder import build_evidence
from src.report.template_reporter import TemplateReporter
from src.report.llm_reporter import LLMReporter, validate_and_render, KEYS


def test_missing_fields_still_produce_evidence_and_template():
    evidence = build_evidence()
    assert set(evidence) == {"meta", "target", "risk_analysis", "behavior_evidence", "graph_evidence", "trace_analysis", "limitations"}
    assert "当前证据不足" in TemplateReporter().generate(evidence)["markdown"]


def test_bad_score_or_fusion_weights_rejected():
    with pytest.raises(ValidationError):
        build_evidence({"risk": {"overall_score": 101}})
    with pytest.raises(ValidationError):
        build_evidence({"risk": {"behavior_weight": .8, "graph_weight": .8}})


def test_llm_references_are_verified():
    evidence = build_evidence({"address_id": "A", "risk": {"overall_score": 92.6, "risk_level": "CRITICAL"}})
    sections = dict.fromkeys(KEYS, "当前证据不足，建议人工复核。")
    sections["overview"] = "地址 {{e:target.address_id}}，风险 {{e:risk_analysis.overall_score}}。"
    assert "92.6" in validate_and_render(sections, evidence)
    sections["graph"] = "邻居风险 99。"
    with pytest.raises(ValueError, match="Unreferenced"):
        validate_and_render(sections, evidence)
    sections["graph"] = "{{e:made_up.path}}"
    with pytest.raises(KeyError):
        validate_and_render(sections, evidence)


def test_api_failure_falls_back_without_crash(tmp_path):
    class BrokenClient:
        @property
        def chat(self):
            raise TimeoutError("simulated timeout")
    reporter = LLMReporter(tmp_path, config={"enabled": True, "base_url": "https://invalid.example/v1",
        "api_key": "test", "model": "test", "temperature": .2, "timeout": 1}, client=BrokenClient())
    result = reporter.generate(build_evidence())
    assert result["source"] == "template" and result["fallback_reason"]


def test_legacy_free_text_candidate_is_not_accepted_by_current_reporter(tmp_path):
    import json
    sections = dict.fromkeys(KEYS, "当前证据不足，建议人工复核。")
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(sections, ensure_ascii=False)))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    reporter = LLMReporter(tmp_path, config={"enabled": True, "base_url": "https://invalid.example/v1",
        "api_key": "test", "model": "test", "temperature": .2, "timeout": 1}, client=client)
    result = reporter.generate(build_evidence())
    assert result["source"] == "template"
    assert result['audit']['candidate_errors'][0]['error_code']=='DOCUMENT_SCHEMA_INVALID'
