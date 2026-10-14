"""Streamlit entry point. Page implementations live in src/ui for readability."""
import streamlit as st
from src.utils.io import ROOT, read_json
from src.ui.runtime import get_service
from src.ui import overview, risk_analysis, tracing, report, evaluation, investigation

st.set_page_config(page_title="Web3 AML · 分析工作台", layout="wide", initial_sidebar_state="auto")
st.markdown("""<style>
 :root {--aml-primary:#1E40AF;--aml-text:#172554;--aml-muted:#475569;--aml-border:#DBEAFE;}
 .block-container {max-width:1440px;padding-top:2.5rem;}
 h1,h2,h3 {color:var(--aml-text);letter-spacing:-.025em;}
 [data-testid="stMetric"] {background:white;border:1px solid var(--aml-border);border-radius:12px;padding:16px;}
 [data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;}
 [data-testid="stSidebar"] {border-right:1px solid var(--aml-border);}
 code {overflow-wrap:anywhere;}
 button:focus-visible,input:focus-visible {outline:3px solid var(--aml-primary);outline-offset:3px;}
 @media(max-width:768px){.block-container{padding:1.5rem 1rem;}h1{font-size:1.8rem;}}
 @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
 </style>""", unsafe_allow_html=True)

required = ["data/processed/metadata.json", "artifacts/risk_scores/risk_scores.parquet", "artifacts/demo_cases.json"]
missing = [p for p in required if not (ROOT / p).exists()]
if missing:
    st.title("Web3 反洗钱分析工作台")
    st.info("首次启动需要先完成离线数据准备和模型训练。")
    st.code("python scripts/00_download_data.py\npython scripts/01_inspect_data.py\npython scripts/02_preprocess.py\npython scripts/03_train_baseline.py\npython scripts/04_train_dual_view.py\npython scripts/05_evaluate.py\npython scripts/06_precompute_scores.py\npython scripts/07_build_demo_cases.py")
    st.stop()

try:
    service = get_service()
except Exception as error:
    st.error(f"分析产物无法加载：{error}。请检查离线流程是否使用同一份数据。")
    st.stop()

cases = read_json(ROOT / "artifacts/demo_cases.json")
st.session_state.setdefault("active_address", cases["high_risk_unknown"][0] if service.predictor.metadata.get('model_kind') == 'evidence_tree' else cases['high_risk_known'][0])
st.session_state.setdefault("address_input", st.session_state["active_address"])


def select_case(group):
    st.session_state["active_address"] = cases[group][0]
    st.session_state["address_input"] = cases[group][0]
    st.session_state["page"] = "地址风险分析"
    st.session_state.pop("trace", None)
    st.session_state.pop("report", None)


with st.sidebar:
    st.markdown("### WEB3 AML")
    st.caption("地址风险评分 · 资金关系追踪 · 可解释报告")
    page = st.radio("分析导航", ["系统总览", "调查优先队列", "地址风险分析", "关系链追踪", "AI 分析报告", "模型评估"], key="page")
    st.divider()
    st.markdown("**比赛示例**")
    for title, group in [("加载高风险示例", "high_risk_known"), ("加载低风险示例", "low_risk_known"),
                         ("加载未知高风险示例", "high_risk_unknown")]:
        st.button(title, on_click=select_case, args=(group,), width="stretch")
    with st.form("address_form"):
        value = st.text_input("地址 / 节点 ID", key="address_input", help="仅支持当前数据集内的地址；数字 ID 使用预处理节点索引。")
        if st.form_submit_button("载入分析地址", width="stretch"):
            try:
                address = service.predictor.resolve(value)
                st.session_state["active_address"] = address
                st.session_state.pop("trace", None)
                st.session_state.pop("report", None)
            except KeyError:
                st.error("未找到该地址或节点 ID，请检查输入或载入预置示例。")
    st.caption("当前地址")
    st.code(st.session_state["active_address"], language=None)
    st.caption("风险分用于人工复核，不构成犯罪认定。")

if service.metadata["scope"] == "real_data_pilot":
    st.warning(f"真实数据子图演示 · {service.metadata['num_nodes']:,} 个地址。指标与路径仅覆盖当前子图，不能代表全量网络。")
address = st.session_state["active_address"]
if page == "系统总览":
    overview.render()
elif page == "调查优先队列":
    investigation.render()
elif page == "地址风险分析":
    risk_analysis.render(address)
elif page == "关系链追踪":
    tracing.render(address)
elif page == "AI 分析报告":
    report.render(address)
else:
    evaluation.render()
