import { modelDisplayName } from './display-metadata.js';
import {
  $,
  $$,
  escape,
  metric,
  toast,
  busy
} from './dom.js';
import {
  state,
  newContext
} from './state.js';
import {
  request
} from './api.js';
import {
  clearPlots
} from './charts.js';
import {
  navigate
} from './navigation.js';
import {
  renderRisk
} from './views/risk.js';
import {
  setTraceDefaults,
  resetTrace,
  traceParameters,
  renderTrace,
  selectPath
} from './views/tracing.js';
import {
  renderReport,
  resetReport,
  selectEvidence,
  returnToStatement,
  renderFault
} from './views/evidence.js';

import {
  setupQueue
} from './views/queue.js';

let initialized = false;
export async function initWorkspace() {
  if (initialized) return;
  initialized = true;
  const queue = setupQueue(loadAddress);
  window.addEventListener('routechange', event => {
    if (event.detail.page === 'workspace' && event.detail.module === 'queue') queue.enter();
  });

  function buttons() {
    const ready = !!state.analysis && !state.loadingAddress;
    $('#trace-button').disabled = !ready || state.loadingTrace || state.loadingReport;
    $('#report-button').disabled = !ready || state.loadingReport || state.loadingTrace || state.traceDirty;
    $('#analyze-button').disabled = state.loadingAddress;
    $('#trace-button').textContent = state.loadingTrace ? '正在搜索关系…' : '运行关系追踪 ↗';
    $('#report-button').textContent = state.loadingReport ? '正在生成报告…' : '生成分析报告 ↗';
    $('#analyze-button').textContent = state.loadingAddress ? '正在评分…' : '开始评分 →';
    $('#report-mode').disabled = state.loadingReport;
    $$('input,select', $('#trace-form')).forEach(input => input.disabled = state.loadingTrace || state
      .loadingReport);
    $('#trace-form').setAttribute('aria-busy', String(state.loadingTrace));
    $('#report-button').setAttribute('aria-busy', String(state.loadingReport));
  }

  function contexts() {
    const address = state.analysis?.address_id || '尚未选择地址';
    $$('.active-address').forEach(el => el.textContent = address);
    $$('.copy-address').forEach(el => el.hidden = !state.analysis);

  }
  async function connect() {
    try {
      state.meta = await request('/meta');
      const meta = state.meta;
      $('#service-state').textContent = '本地服务已就绪';
      $('#reconnect').hidden = true;
      $('#workspace-model').textContent = modelDisplayName;
      $('#footer-data').textContent = modelDisplayName;
      $('#example-buttons').innerHTML = '<span>快捷示例</span>' + [
        ['high_risk_known', '已知高风险示例'],
        ['low_risk_known', '低风险示例'],
        ['high_risk_unknown', '未知标签高风险示例']
      ].map(([key, label]) => `<button type="button" data-example="${key}">${label}</button>`).join('');
      $$('[data-example]').forEach(button => button.addEventListener('click', () => loadAddress(meta
        .examples[
          button.dataset.example][0])));
      $('#risk-counts').innerHTML = Object.entries(meta.risk_counts).map(([level, count]) => metric(level,
        count.toLocaleString())).join('');
      setTraceDefaults(meta, $('#trace-mode').value === 'long');
      $('#long-case-select').innerHTML = meta.long_cases.map(item =>
          `<option value="${escape(item.address_id)}">${item.hops} 跳 · ${escape(item.address_id)}</option>`
          )
        .join('');
      $('#load-long-case').disabled = !meta.long_cases.length;
    } catch (error) {
      $('#service-state').textContent = '服务未就绪';
      $('#reconnect').hidden = false;
      $('#address-error').textContent = error.message;
    }
  }
  $('#reconnect').addEventListener('click', async () => {
    await connect();
    queue.reload();
  });
  let riskController;
  async function loadAddress(address, options = {}) {
    if (!address.trim()) {
      $('#address-error').textContent = '请输入地址或节点 ID。';
      return;
    }
    riskController?.abort();
    riskController = new AbortController();
    const token = newContext();
    state.loadingAddress = true;
    $('#address-input').value = address;
    $('#address-error').textContent = '';
    clearPlots('#risk-results');
    $('#risk-results').hidden = true;
    $('#risk-empty').hidden = false;
    $('#risk-empty h3').textContent = '正在读取地址风险与解释…';
    $('#risk-empty p').textContent = '正在使用本地模型和数据快照。';
    resetTrace();
    resetReport();
    contexts();
    buttons();
    try {
      const record = await request('/risk?address=' + encodeURIComponent(address), {
        signal: riskController.signal
      });
      if (token !== state.epoch) return;
      state.analysis = record;
      renderRisk(record);
      contexts();
      $('#risk-empty h3').textContent = '从地址开始，展开分析';
      $('#risk-empty p').textContent = '选择一个示例，即可查看真实评分与模型证据。';
      $('#report-help').textContent = '尚未追踪时，将先按默认参数生成关系路径。';
      if (options.long) {
        $('#trace-mode').value = 'long';
        setTraceDefaults(state.meta, true);
        if (state.page === 'workspace') navigate('#relation-tracing');
      }
      toast('地址评分已载入');
    } catch (error) {
      if (token !== state.epoch) return;
      $('#address-error').textContent = error.message;
      $('#risk-empty h3').textContent = '尚未获得分析结果';
      $('#risk-empty p').textContent = '检查地址或选择示例后重试；仅支持当前数据快照。';
    } finally {
      if (token === state.epoch) {
        state.loadingAddress = false;
        buttons();
      }
    }
  }
  $('#address-form').addEventListener('submit', event => {
    event.preventDefault();
    loadAddress($('#address-input').value);
  });
  $$('.copy-address').forEach(button => button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(state.analysis.address_id);
      toast('完整地址已复制');
    } catch {
      toast('复制失败，请选择地址文本手动复制');
    }
  }));
  $('#max-depth').addEventListener('input', () => $('#depth-output').textContent = $('#max-depth').value +
    ' 跳');

  function parametersChanged() {
    if (!state.trace) return;
    state.traceDirty = true;
    $('#trace-stale').hidden = false;
    $('#trace-stale').textContent = '参数已修改。当前图仍对应上次实际运行参数，请重新运行以更新结果。';
    state.report = null;
    resetReport();
    $('#report-help').textContent = '参数已修改，请先重新运行关系追踪，再生成对应报告。';
    buttons();
  }
  $('#trace-form').addEventListener('input', parametersChanged);
  $('#trace-mode').addEventListener('change', () => {
    if (state.meta) setTraceDefaults(state.meta, $('#trace-mode').value === 'long');
    parametersChanged();
  });
  $('#load-long-case').addEventListener('click', () => loadAddress($('#long-case-select').value, {
    long: true
  }));
  $('#trace-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.analysis) return;
    const token = state.epoch,
      traceToken = ++state.traceEpoch,
      params = traceParameters(),
      mode = $('#trace-mode').value;
    state.loadingTrace = true;
    state.report = null;
    resetReport();
    $('#trace-error').textContent = '';
    $('#graph-state').textContent = '正在搜索…';
    buttons();
    try {
      const result = await request('/traces', {
        body: {
          analysis_id: state.analysis.analysis_id,
          params,
          mode
        }
      });
      if (token !== state.epoch || traceToken !== state.traceEpoch) return;
      state.trace = result;
      state.traceDirty = false;
      renderTrace(result);
      $('#report-help').textContent = '将使用当前追踪结果生成报告。';
      toast('关系追踪已完成');
    } catch (error) {
      if (token === state.epoch) {
        $('#trace-error').textContent = error.message;
        $('#graph-state').textContent = '追踪失败，可重试';
      }
    } finally {
      if (token === state.epoch && traceToken === state.traceEpoch) {
        state.loadingTrace = false;
        buttons();
      }
    }
  });
  $('#path-select').addEventListener('change', () => {
    if (state.trace) selectPath(state.trace, Number($('#path-select').value));
  });
  $('#report-button').addEventListener('click', async () => {
    if (!state.analysis) return;
    if (state.traceDirty) {
      $('#report-error').textContent = '追踪参数已修改，请重新运行关系追踪。';
      return;
    }
    const token = state.epoch,
      traceToken = state.traceEpoch;
    state.loadingReport = true;
    $('#report-error').textContent = '';
    // Keep the last record for failure recovery, but hide its warning while retrying.
    $('#report-results').hidden = true;
    $('#report-empty').hidden = true;
    $('#report-fallback').hidden = true;
    $('#report-status').textContent = state.trace ? '正在组织固定证据并生成报告…' : '正在使用默认参数追踪，随后生成报告…';
    buttons();
    try {
      const record = await request('/reports', {
        body: {
          analysis_id: state.analysis.analysis_id,
          trace_id: state.trace?.trace_id || null,
          mode: $('#report-mode').value
        }
      });
      if (token !== state.epoch || traceToken !== state.traceEpoch) return;
      if (record.generated_trace) {
        state.trace = record.generated_trace;
        renderTrace(state.trace);
      }
      state.report = record;
      renderReport(record);
      $('#report-status').textContent = '报告已生成，点击证据编号核对来源。';
      $('#report-help').textContent = '报告与当前评分、追踪快照绑定。';
      toast('报告与证据已就绪');
    } catch (error) {
      if (token === state.epoch) {
        if (state.report) renderReport(state.report);
        else $('#report-empty').hidden = false;
        $('#report-error').textContent = error.message + (state.report ? ' 下方保留上一次生成的报告。' : '');
      }
    } finally {
      if (token === state.epoch) {
        state.loadingReport = false;
        buttons();
        if (!state.report) $('#report-status').textContent = '';
      }
    }
  });
  $('#evidence-select').addEventListener('change', () => selectEvidence($('#evidence-select').value));
  $('#return-statement').addEventListener('click', returnToStatement);
  $('#fault-button').addEventListener('click', async () => {
    if (!state.report) return;
    const token = state.epoch,
      id = state.report.report_id;
    busy($('#fault-button'), true, '正在运行模拟核验…');
    try {
      const result = await request(`/reports/${id}/demo`, {
        body: {
          kind: $('#fault-kind').value
        }
      });
      if (token === state.epoch && id === state.report?.report_id) renderFault(result);
    } catch (error) {
      if (token === state.epoch && id === state.report?.report_id) $('#fault-result').textContent =
        error.message;
    } finally {
      busy($('#fault-button'), false, '运行核验演示');
    }
  });
  buttons();

  await connect();
}
