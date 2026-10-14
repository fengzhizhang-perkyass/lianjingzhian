import streamlit as st
from src.inference.analysis_service import AnalysisService
from src.utils.io import ROOT, read_json, artifact_key, file_sha256
from src.tracing.budgeted_tracer import stable_hash


@st.cache_resource(max_entries=1)
def service(fingerprint):
    return AnalysisService()


def get_service():
    overlay = ROOT / "artifacts/investigation/metadata.json"
    active = read_json(ROOT / 'artifacts/risk_scores/metadata.json')
    token = (read_json(ROOT / "data/processed/metadata.json")["fingerprint"],
             read_json(ROOT / "artifacts/risk_scores/metadata.json").get("risk_revision", "legacy"),
             read_json(overlay)["revision"] if overlay.exists() and active.get('model_kind') != 'evidence_tree' else None,
             stable_hash({str(path.relative_to(ROOT)):file_sha256(path) for path in (
                 ROOT/'config/tracing.yaml',ROOT/'config/reporting.yaml',ROOT/'src/inference/analysis_service.py',
                 *([ROOT/'artifacts/reporting/source_index.json'] if (ROOT/'artifacts/reporting/source_index.json').exists() else []),
                 *sorted((ROOT/'src/tracing').glob('*.py')),*sorted((ROOT/'src/report').glob('*.py')))}))
    if st.session_state.get("artifact_revision") != token:
        st.session_state.pop("trace", None)
        st.session_state.pop("report", None)
        st.session_state["artifact_revision"] = token
    return service(token)


@st.cache_data(max_entries=128, show_spinner=False)
def analysis(address, fingerprint):
    key = artifact_key(address)
    cached = ROOT / "artifacts/reports" / f"{key}_analysis.json"
    # Cached pilot cases belong to the same graph only when their evidence fingerprint agrees.
    evidence_path = cached.with_name(f"{key}_evidence.json")
    if cached.exists() and evidence_path.exists():
        evidence = read_json(evidence_path)
        if (evidence["meta"].get("dataset_fingerprint") == fingerprint[0]
                and evidence["meta"].get("risk_revision", "legacy") == fingerprint[1]
                and evidence["meta"].get("investigation_revision") == fingerprint[2]):
            return read_json(cached)
    return service(fingerprint).analyze(address)


def get_analysis(address):
    get_service()
    return analysis(address,st.session_state['artifact_revision'])
