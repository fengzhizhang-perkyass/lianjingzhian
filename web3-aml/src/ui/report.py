import json
import streamlit as st
from src.ui.runtime import get_service, get_analysis


def render(address):
    st.title("AI 分析报告")
    st.code(address, language=None)
    st.write("每条声明绑定具体证据，核对类型、主体、单位和来源。点击证据编号可定位字段、特征或路径；LLM不可改写事实值。")
    if st.button("生成 AML 分析报告", type="primary"):
        with st.spinner("正在组织证据并生成报告…"):
            service = get_service()
            trace = st.session_state.get("trace")
            if not trace or trace["seed_address"] != address:
                trace = service.trace(address)
                st.session_state["trace"] = trace
            evidence = service.evidence(get_analysis(address), trace)
            st.session_state["report"] = {"address": address, "evidence": evidence, **service.report(evidence)}
    report = st.session_state.get("report")
    if not report or report["address"] != address:
        st.info("点击生成报告。如果还未运行追踪，将使用默认参数生成关系路径。")
        return
    if report["fallback_reason"]:
        st.info(report["fallback_reason"])
    st.caption("报告来源："+("LLM组织声明 · 协议事实已核验" if report["source"] == "llm" else "结构化证据模板 · 协议事实已核验"))
    if report.get('protocol')=='report_claims_v1':
        from src.ui.report_evidence import render as render_audited, render_fault_demo
        render_audited(report)
        render_fault_demo(report,get_service())
    else:
        st.markdown(report["markdown"])
    columns = st.columns(3)
    columns[0].download_button("下载 Markdown", report["markdown"], "aml_report.md", "text/markdown")
    columns[1].download_button("下载 TXT", report["markdown"], "aml_report.txt", "text/plain")
    columns[2].download_button("下载 Evidence JSON", json.dumps(report["evidence"], ensure_ascii=False, indent=2),
                               "evidence.json", "application/json")
    with st.expander("查看完整 Evidence JSON"):
        st.json(report["evidence"])
