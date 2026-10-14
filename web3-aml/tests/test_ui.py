"""Exercise all five pages with real saved artifacts, when the offline pipeline is ready."""
import pytest
from src.utils.io import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "artifacts/demo_cases.json").exists(), reason="Offline demo artifacts not built yet")


def test_five_pages_and_report_fallback():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not app.exception
    for page in ["地址风险分析", "关系链追踪", "AI 分析报告", "模型评估"]:
        app.radio(key="page").set_value(page).run()
        assert not app.exception, str(app.exception)
        if page == "关系链追踪":
            app.button(key="FormSubmitter:trace_parameters-运行关系链追踪").click().run()
            assert not app.exception
        elif page == "AI 分析报告":
            next(button for button in app.button if button.label == "生成 AML 分析报告").click().run()
            assert not app.exception
            assert any("Web3 AML 风险分析报告" in item.value for item in app.markdown)
    # Case callbacks switch input and page before widgets render.
    next(button for button in app.button if button.label == "加载低风险示例").click().run()
    assert not app.exception and app.radio(key="page").value == "地址风险分析"


@pytest.mark.skipif(not (ROOT / "artifacts/investigation/metadata.json").exists(), reason="Investigation overlay not built")
def test_investigation_queue_strategies_drilldown_and_evidence():
    from streamlit.testing.v1 import AppTest
    from src.utils.io import read_json
    overlay = read_json(ROOT / "artifacts/investigation/metadata.json")
    base = read_json(ROOT / "artifacts/risk_scores/metadata.json")
    if overlay["risk_revision"] != base.get("risk_revision"):
        pytest.skip("Investigation overlay belongs to a previous base model")
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    app.radio(key="page").set_value("调查优先队列").run()
    assert not app.exception, str(app.exception)
    for strategy in ["分歧复核", "排序上调", "优先排查"]:
        app.radio(key="investigation_strategy").set_value(strategy).run()
        assert not app.exception, str(app.exception)
    target = app.selectbox(key="queue_address_优先排查").value
    next(button for button in app.button if button.label == "查看该地址的风险与证据").click().run()
    assert not app.exception and app.radio(key="page").value == "地址风险分析"
    assert app.session_state["active_address"] == target
    assert any("调查优先级与专家诊断" in heading.value for heading in app.subheader)
    app.radio(key="page").set_value("AI 分析报告").run()
    next(button for button in app.button if button.label == "生成 AML 分析报告").click().run()
    assert not app.exception
    assert any("拓扑树专家" in text.value for text in app.markdown)


def test_current_evidence_model_queue_and_three_responsibilities():
    from src.utils.io import read_json
    if read_json(ROOT / 'artifacts/risk_scores/metadata.json').get('model_kind') != 'evidence_tree':
        pytest.skip('Evidence model not activated')
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
    app.radio(key='page').set_value('调查优先队列').run()
    assert not app.exception
    target = app.selectbox(key='evidence_queue_address').value
    next(button for button in app.button if button.label == '查看该地址的风险与证据').click().run()
    assert not app.exception and app.session_state['active_address'] == target
    assert any('三类证据各自负责什么' in heading.value for heading in app.subheader)
    assert not any('自适应融合系数' in heading.value for heading in app.subheader)
