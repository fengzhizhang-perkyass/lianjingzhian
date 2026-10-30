import { $, $$, escape, number, levelName, table, riskScoreHTML, riskLevelsHTML } from '../dom.js';
import { request, downloadPath } from '../api.js';
import { state, datasetContext } from '../state.js';
import { navigate } from '../navigation.js';

export function setupQueue(onChoose, onReport) {
  $('#queue-level-guide').innerHTML=riskLevelsHTML();
  const pageInput=$('#queue-page-input');
  const pageCount=q=>Math.ceil(q.total/q.limit);
  function clearPageError(){
    $('#queue-page-error').hidden=true;
    $('#queue-page-error').textContent='';
    pageInput.removeAttribute('aria-invalid');
  }
  function renderPagination(q){
    const total=pageCount(q),page=total?Math.floor(q.offset/q.limit)+1:0;
    pageInput.value=String(page);
    pageInput.max=String(Math.max(1,total));
    pageInput.disabled=q.loading||!q.result||!total;
    $('#queue-limit').disabled=q.loading;
    $('#queue-total-pages').textContent=`共${total.toLocaleString('zh-CN')}页`;
    $('#queue-prev').disabled=q.loading||!q.result||q.offset===0;
    $('#queue-next').disabled=q.loading||!q.result||q.offset+q.limit>=q.total;
    $('#queue-page').textContent=q.loading?`正在读取第${page||1}页`:
      !q.result?'队列尚未载入':total?`第${page}页，共${total}页；显示第${q.offset+1}至${Math.min(q.offset+q.limit,q.total)}条`:'暂无可展示的队列';
  }
  function render(id) {
    if (id !== state.datasetId) return;
    const q = datasetContext(id).queue;
    $('#queue-limit').value = String(q.limit);
    clearPageError();renderPagination(q);
    if (!q.result) { $('#queue-table').textContent = q.loading ? '正在读取当前数据集队列…' : '当前队列尚未载入。'; return; }
    const result = q.result;
    table('#queue-table', [
      {label:'风险排名',key:'risk_rank'}, {label:'地址',key:'address_id',mono:true},
      {label:'综合风险',render:r=>riskScoreHTML(r.overall_risk_score)},
      {label:'等级',render:r=>escape(levelName(r.risk_level))},
      {label:'操作',render:(_,i)=>`<div class="queue-actions"><button type="button" data-queue-index="${i}">查看风险 →</button><button type="button" class="text-button" data-report-index="${i}">生成研判</button></div>`}
    ],result.rows || []);
    $$('[data-queue-index]',$('#queue-table')).forEach(b=>b.addEventListener('click',()=>{
      navigate('#risk-scoring'); onChoose(result.rows[Number(b.dataset.queueIndex)].address_id);
    }));
    $$('[data-report-index]',$('#queue-table')).forEach(b=>b.addEventListener('click',()=>{
      onReport(result.rows[Number(b.dataset.reportIndex)].address_id);
    }));
    $('#queue-download').href=downloadPath(`/queue/export?limit=${q.limit}&offset=${q.offset}`,id);
  }
  async function loadQueue(id=state.datasetId) {
    const q=datasetContext(id).queue, sequence=++q.sequence;
    q.loading=true;
    if(id===state.datasetId) { render(id); $('#queue-table').setAttribute('aria-busy','true'); }
    try {
      const result=await request(`/queue?limit=${q.limit}&offset=${q.offset}`,{datasetId:id});
      if(sequence!==q.sequence)return;
      q.total=result.total; q.result=result;
    } catch(error) {
      if(sequence!==q.sequence)return;
      q.result=null;
      if(id===state.datasetId)$('#queue-table').textContent=error.message;
    } finally {
      if(sequence===q.sequence){q.loading=false; if(id===state.datasetId){if(q.result)render(id);else renderPagination(q);$('#queue-table').removeAttribute('aria-busy');}}
    }
  }
  function jumpToPage(){
    const q=state.queue;if(q.loading||!q.result||!q.total)return;
    const text=pageInput.value.trim(),page=Number(text),total=pageCount(q);
    if(!/^\d+$/.test(text)||!Number.isSafeInteger(page)||page<1||page>total){
      pageInput.setAttribute('aria-invalid','true');
      $('#queue-page-error').textContent=`请输入1至${total.toLocaleString('zh-CN')}之间的整数页码。`;
      $('#queue-page-error').hidden=false;return;
    }
    clearPageError();
    const offset=(page-1)*q.limit;
    if(offset===q.offset){pageInput.value=String(page);return;}
    q.offset=offset;loadQueue();
  }
  $('#queue-page-form').addEventListener('submit',event=>{event.preventDefault();jumpToPage();});
  pageInput.addEventListener('change',jumpToPage);
  pageInput.addEventListener('input',clearPageError);
  $('#queue-limit').addEventListener('change',()=>{const q=state.queue;q.limit=Number($('#queue-limit').value);q.offset=0;loadQueue();});
  $('#queue-prev').addEventListener('click',()=>{state.queue.offset=Math.max(0,state.queue.offset-state.queue.limit);loadQueue();});
  $('#queue-next').addEventListener('click',()=>{state.queue.offset+=state.queue.limit;loadQueue();});
  return {enter(){if(!state.queue.result&&!state.queue.loading)loadQueue();else render(state.datasetId);},reload(){loadQueue();},render(){render(state.datasetId);}};
}
