import {
  $,
  $$,
  escape,
  number,
  levelName,
  table
} from '../dom.js';
import {
  request
} from '../api.js';
import {
  navigate
} from '../navigation.js';

export function setupQueue(onChoose) {

  let offset = 0,
    total = 0,
    requestSequence = 0;
  let loaded = false,
    loading = false;
  async function loadQueue() {
    loading = true;
    const sequence = ++requestSequence,
      limit = Number($('#queue-limit').value);
    $('#queue-table').setAttribute('aria-busy', 'true');
    try {
      const result = await request(`/queue?limit=${limit}&offset=${offset}`);
      if (sequence !== requestSequence) return;
      total = result.total;
      loaded = true;
      table('#queue-table', [{
        label: '风险排名',
        key: 'risk_rank'
      }, {
        label: '地址',
        key: 'address_id',
        mono: true
      }, {
        label: '综合风险',
        render: r => number(r.overall_risk_score)
      }, {
        label: '等级',
        render: r => escape(levelName(r.risk_level))
      }, {
        label: '行为诊断',
        render: r => number(r.behavior_score)
      }, {
        label: '偏离诊断',
        render: r => number(r.graph_score)
      }, {
        label: '结构诊断',
        render: r => number(r.structure_score)
      }, {
        label: '操作',
        render: (_, i) => `<button type="button" data-queue-index="${i}">核查地址 →</button>`
      }], result.rows);
      $$('[data-queue-index]', $('#queue-table')).forEach(button => button.addEventListener('click', () => {
        navigate('#risk-scoring');
        onChoose(result.rows[Number(button.dataset.queueIndex)].address_id);
      }));
      $('#queue-page').textContent =
        `${offset+1}–${Math.min(offset+limit,total)} / ${total.toLocaleString()}`;
      $('#queue-prev').disabled = offset === 0;
      $('#queue-next').disabled = offset + limit >= total;
      $('#queue-download').href = `/api/queue/export?limit=${limit}&offset=${offset}`;
    } catch (error) {
      loaded = false;
      $('#queue-table').textContent = error.message;
    } finally {
      if (sequence === requestSequence) {
        loading = false;
        $('#queue-table').removeAttribute('aria-busy');
      }
    }
  }
  $('#queue-limit').addEventListener('change', () => {
    offset = 0;
    loadQueue();
  });
  $('#queue-prev').addEventListener('click', () => {
    offset = Math.max(0, offset - Number($('#queue-limit').value));
    loadQueue();
  });
  $('#queue-next').addEventListener('click', () => {
    offset += Number($('#queue-limit').value);
    loadQueue();
  });
  return {
    enter() {
      if (!loaded && !loading) loadQueue();
    },
    reload() {
      loaded = false;
      loadQueue();
    }
  };
}
