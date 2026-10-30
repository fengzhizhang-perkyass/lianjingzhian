import { $, $$, escape, metric, toast, busy, levelName } from './dom.js';
import { state, datasetContext, datasetLabel, datasetIds, selectDataset, newContext } from './state.js';
import { request } from './api.js';
import { clearPlots } from './charts.js';
import { navigate } from './navigation.js';
import { goWorkspace, setDatasetHandler } from './router.js';
import { renderRisk } from './views/risk.js';
import { setTraceDefaults, resetTrace, traceParameters, renderTrace, selectPath } from './views/tracing.js';
import { renderReport, resetReport, selectEvidence, returnToStatement, renderFault } from './views/evidence.js';
import { setupQueue } from './views/queue.js';
import { updateGroupControls } from './groups.js';

let initialized=false;
const polling=new Set();
const stageNames={queued:'排队中',risk:'地址风险识别',trace:'多跳关联追踪',generation:'AI组织报告',validation:'证据核验',completed:'报告已完成',failed:'任务失败',interrupted:'任务已中断'};
const terminal=job=>['completed','failed','interrupted'].includes(job?.status);
export async function initWorkspace(){
  if(initialized)return;
  initialized=true;
  const queue=setupQueue(loadAddress,address=>{setReportTarget(datasetContext(state.datasetId),address,true);goWorkspace('report');$('#report-address-input').value=address;$('#report-address-input').focus();});
  const active=(id,ctx,token=ctx.epoch)=>state.datasetId===id&&ctx.epoch===token;
  function buttons(){
    const c=datasetContext(state.datasetId),ready=!!c.analysis&&!c.loadingAddress;
    $('#trace-button').disabled=!ready||c.loadingTrace||c.loadingReport;
    $('#analyze-button').disabled=c.loadingAddress||c.loadingReport;
    $('#direct-report-button').disabled=c.loadingReport||c.loadingAddress||c.loadingTrace;
    $('#report-address-input').disabled=c.loadingReport;
    $('#trace-button').textContent=c.loadingTrace?'正在搜索关联…':'运行多跳追踪 ↗';
    $('#direct-report-button').textContent=c.loadingReport?'正在生成可信研判…':'一键生成可信研判 →';
    $('#analyze-button').textContent=c.loadingAddress?'正在读取评分…':'开始识别 →';
    $('#report-mode').disabled=c.loadingReport;
    $$('input,select',$('#trace-form')).forEach(el=>el.disabled=c.loadingTrace||c.loadingReport);
    $('#trace-form').setAttribute('aria-busy',String(c.loadingTrace));
    $('#report-address-form').setAttribute('aria-busy',String(c.loadingReport));
    updateGroupControls();
  }
  function setReportTarget(c,address,edited=false){
    c.reportDraft=address||'';c.reportDraftDirty=edited;c.reportDraftAddress=c.analysis?.address_id||null;
  }
  function syncReportTarget(c){
    if(c.analysis&&!c.reportDraftDirty&&c.reportDraftAddress===null)setReportTarget(c,c.analysis.address_id);
    if($('#report-address-input').value!==c.reportDraft)$('#report-address-input').value=c.reportDraft;
    $('#report-help').textContent=c.traceDirty?'追踪参数已修改，生成时会使用当前参数更新路径。':c.analysis?'自动复用当前地址的有效评分与追踪；编辑地址后为新对象生成。':'输入当前数据集中的地址，即可自动完成识别、追踪与核验。';
  }
  function contexts(){
    const address=state.analysis?.address_id||'尚未选择地址';
    $$('.active-address').forEach(el=>el.textContent=address);
    $('#dataset-active-address').textContent=address;
    $$('.copy-address').forEach(el=>el.hidden=!state.analysis);
    $$('.dataset-label').forEach(el=>el.textContent=datasetLabel(state.datasetId));
    $('#dataset-select').value=state.datasetId;
    syncReportTarget(datasetContext(state.datasetId));
  }
  function renderMeta(){
    const m=state.meta;if(!m)return;
    $('#service-state').textContent=datasetLabel(state.datasetId)+'数据集已就绪';$('#reconnect').hidden=true;
    $('#dataset-description').textContent=state.datasetId==='ethereum'?'SA-DCF · 结构–属性双视图协同融合':'多维交易证据 · 地址风险识别';
    $('#footer-data').textContent='风险识别 · 关联追踪 · 可信研判';
    const examples=[['high_risk_known','高风险示例'],['low_risk_known','低风险示例'],['high_risk_unknown','其他高风险示例']].filter(([key])=>m.examples?.[key]?.length);
    $('#example-buttons').innerHTML='<span>快捷示例</span>'+examples.map(([key,label])=>`<button type="button" data-example="${key}">${label}</button>`).join('');
    $$('[data-example]').forEach(b=>b.addEventListener('click',()=>loadAddress(m.examples[b.dataset.example][0])));
    $('#risk-counts').innerHTML=Object.entries(m.risk_counts||{}).map(([level,count])=>metric(levelName(level),Number(count).toLocaleString())).join('');
    $('#long-case-select').innerHTML=(m.long_cases||[]).map(x=>`<option value="${escape(x.address_id)}">${x.hops} 跳 · ${escape(x.address_id)}</option>`).join('');
    $('#load-long-case').disabled=!(m.long_cases||[]).length;
  }
  async function connect(id=state.datasetId){
    const c=datasetContext(id);
    try{c.meta=await request('/meta',{datasetId:id});if(state.datasetId===id){renderMeta();if(!c.traceForm)setTraceDefaults(c.meta,c.traceMode==='long');}}
    catch(error){if(state.datasetId===id){$('#service-state').textContent=datasetLabel(id)+'服务未就绪';$('#reconnect').hidden=false;$('#address-error').textContent=error.message;$('#dataset-description').textContent='数据或服务正在准备，请稍后重试。';}}
  }
  function stashUI(){
    const c=datasetContext(state.datasetId);c.addressDraft=$('#address-input').value;c.reportDraft=$('#report-address-input').value;
    c.traceForm=traceParameters();c.traceMode=$('#trace-mode').value;c.reportMode=$('#report-mode').value;
    c.pathIndex=$('#path-select').value;c.evidenceLabel=$('#evidence-select').value;
  }
  function renderJob(c){
    const el=$('#report-job-stages');el.hidden=!c.job;
    if(c.jobError)$('#report-address-error').textContent=c.jobError;
    if(!c.job)return;
    const stage=c.job.stage||c.job.status,keys=['risk','trace','generation','validation'],index=keys.indexOf(stage);
    el.innerHTML=keys.map((key,i)=>`<span class="${stage==='completed'||i<index?'done':key===stage?'current':''}"><b>${i+1}</b>${stageNames[key]}</span>`).join('')+`<p>${escape(c.job.message||stageNames[stage]||'正在准备分析任务')}</p>`;
  }
  function restoreUI(){
    const c=datasetContext(state.datasetId);
    clearPlots('#risk-results');$('#risk-results').hidden=!c.analysis;$('#risk-empty').hidden=!!c.analysis;
    $('#risk-empty h3').textContent='从地址开始，展开分析';$('#risk-empty p').textContent='输入当前数据集中的地址，或选择真实示例查看风险依据。';
    $('#address-error').textContent='';$('#report-address-error').textContent='';
    resetTrace();resetReport();busy($('#fault-button'),false,'运行核验演示');$('#report-cross-links').hidden=true;
    $('#address-input').value=c.addressDraft;$('#report-address-input').value=c.reportDraft;$('#report-mode').value=c.reportMode;
    renderMeta();contexts();
    if(c.analysis)renderRisk(c.analysis);
    if(c.trace){renderTrace(c.trace);const i=Number(c.pathIndex);if(c.pathIndex!==null&&c.trace.result.top_paths[i]){$('#path-select').value=String(i);selectPath(c.trace,i);}}
    else if(c.meta)setTraceDefaults(c.meta,c.traceMode==='long');
    $('#trace-mode').value=c.traceMode;
    if(c.traceForm)for(const [key,value] of Object.entries(c.traceForm)){const el=$(`[name="${key}"]`,$('#trace-form'));if(el)el.value=value;}
    $('#depth-output').textContent=$('#max-depth').value+' 跳';
    if(c.traceDirty){$('#trace-stale').hidden=false;$('#trace-stale').textContent='参数已修改，当前图仍对应上次运行参数。请重新运行追踪。';}
    if(c.report){renderReport(c.report);if(c.evidenceLabel)selectEvidence(c.evidenceLabel);$('#report-cross-links').hidden=false;}
    renderJob(c);buttons();queue.render();
    if(c.job&&!terminal(c.job))pollJob(state.datasetId,c.job.job_id,c.job.clientEpoch);
  }
  async function switchDataset(id,navigateAfter=true){
    if(!datasetIds.includes(id)){toast('不支持该数据集，请选择比特币或以太坊。');return;}
    if(id===state.datasetId)return;
    stashUI();const oldModule=state.module;selectDataset(id);contexts();restoreUI();
    if(!state.meta)await connect(id);
    if(state.datasetId!==id)return;
    renderMeta();buttons();queue.enter();
    if(navigateAfter)await goWorkspace(state.lastModule||oldModule,id);
  }
  setDatasetHandler(switchDataset);
  $('#dataset-select').addEventListener('change',event=>switchDataset(event.target.value));
  $('#reconnect').addEventListener('click',async()=>{await connect();queue.reload();});
  window.addEventListener('routechange',event=>{if(event.detail.page==='workspace'){contexts();if(event.detail.module==='queue')queue.enter();}});
  $('#address-input').addEventListener('input',()=>state.addressDraft=$('#address-input').value);
  $('#report-address-input').addEventListener('input',()=>{state.reportDraft=$('#report-address-input').value;state.reportDraftDirty=true;});
  $('#report-mode').addEventListener('change',()=>state.reportMode=$('#report-mode').value);
  async function loadAddress(address,options={}){
    if(!address?.trim()){$('#address-error').textContent='请输入地址或节点 ID。';return;}
    const id=state.datasetId,c=datasetContext(id);
    if(c.loadingReport){toast('当前数据集正在生成报告，请稍后再切换地址。');return;}
    const token=newContext(id);c.job=null;c.jobError='';c.addressDraft=address;c.loadingAddress=true;
    restoreUI();$('#address-input').value=address;$('#risk-empty h3').textContent='正在读取地址风险与真实解释…';
    try{
      const record=await request('/risk?address='+encodeURIComponent(address),{datasetId:id});
      if(c.epoch!==token)return;c.analysis=record;setReportTarget(c,record.address_id);
      if(active(id,c,token)){renderRisk(record);contexts();$('#report-help').textContent='自动复用当前地址的有效评分，缺少追踪时会自动补齐。';if(options.long){$('#trace-mode').value='long';c.traceMode='long';setTraceDefaults(c.meta,true);for(const [key,value] of Object.entries(options.traceConfig||{})){const input=$(`[name="${key}"]`,$('#trace-form'));if(input)input.value=value;}c.traceForm=traceParameters();$('#depth-output').textContent=$('#max-depth').value+' 跳';navigate('#relation-tracing');}toast('地址风险与证据已载入');}
    }catch(error){if(active(id,c,token)){$('#address-error').textContent=error.message;$('#risk-empty h3').textContent='当前地址未能完成识别';$('#risk-empty p').textContent='请检查输入是否属于所选数据集。';}}
    finally{if(c.epoch===token){c.loadingAddress=false;if(state.datasetId===id)buttons();}}
  }
  $('#address-form').addEventListener('submit',event=>{event.preventDefault();loadAddress($('#address-input').value);});
  $$('.copy-address').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(state.analysis.address_id);toast('完整地址已复制');}catch{toast('请选择地址文本手动复制');}}));
  $('#max-depth').addEventListener('input',()=>$('#depth-output').textContent=$('#max-depth').value+' 跳');
  function parametersChanged(){
    state.traceForm=traceParameters();state.traceMode=$('#trace-mode').value;if(!state.trace)return;
    state.traceDirty=true;state.report=null;resetReport();$('#report-cross-links').hidden=true;
    $('#trace-stale').hidden=false;$('#trace-stale').textContent='参数已修改，当前图仍对应上次运行参数。请重新运行以更新结果。';
    $('#report-help').textContent='追踪参数已修改，生成报告时会使用当前参数更新路径。';buttons();
  }
  $('#trace-form').addEventListener('input',parametersChanged);
  $('#trace-mode').addEventListener('change',()=>{if(state.meta)setTraceDefaults(state.meta,$('#trace-mode').value==='long');parametersChanged();});
  $('#load-long-case').addEventListener('click',()=>{const address=$('#long-case-select').value,example=(state.meta?.long_cases||[]).find(x=>x.address_id===address);loadAddress(address,{long:true,traceConfig:example?.trace_config});});
  $('#trace-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!state.analysis)return;
    const id=state.datasetId,c=datasetContext(id),token=c.epoch,traceToken=++c.traceEpoch,params=traceParameters(),mode=$('#trace-mode').value;
    c.loadingTrace=true;c.report=null;resetReport();$('#report-cross-links').hidden=true;$('#trace-error').textContent='';$('#graph-state').textContent='正在搜索…';buttons();
    try{
      const result=await request('/traces',{datasetId:id,body:{analysis_id:c.analysis.analysis_id,params,mode}});
      if(c.epoch!==token||c.traceEpoch!==traceToken)return;c.trace=result;c.traceDirty=false;c.pathIndex=null;c.traceForm=params;c.traceMode=mode;
      if(active(id,c,token)){renderTrace(result);$('#report-help').textContent='将使用当前追踪结果生成报告。';toast('多跳关联追踪已完成');}
    }catch(error){if(active(id,c,token)){$('#trace-error').textContent=error.message;$('#graph-state').textContent='追踪失败，可重试';}}
    finally{if(c.epoch===token&&c.traceEpoch===traceToken){c.loadingTrace=false;if(state.datasetId===id)buttons();}}
  });
  $('#path-select').addEventListener('change',()=>{state.pathIndex=$('#path-select').value;if(state.trace)selectPath(state.trace,Number(state.pathIndex));});
  async function pollJob(id,jobId,token){
    const key=id+':'+jobId;if(polling.has(key))return;polling.add(key);
    const c=datasetContext(id);
    try{
      while(c.job?.job_id===jobId&&c.epoch===token){
        if(state.datasetId!==id)return;
        const job=await request('/jobs/'+encodeURIComponent(jobId),{datasetId:id,timeout:30000});
        if(c.job?.job_id!==jobId||c.epoch!==token)return;
        c.job={...job,clientEpoch:token};
        if(job.status==='completed'){
          const result=job.result;
          if(!result?.report)throw new Error('报告任务已结束，但结果记录不完整，请重试。');
          if(result.versions&&!sameVersions(result.versions,c.meta?.versions)){
            await connect(id);
            if(c.job?.job_id!==jobId||c.epoch!==token)return;
          }
          if(result.analysis?.analysis_id){c.analysis=result.analysis;c.addressDraft=c.analysis.address_id;setReportTarget(c,c.analysis.address_id);}
          if(result.trace?.trace_id)c.trace=result.trace;else if(result.generated_trace?.trace_id)c.trace=result.generated_trace;
          c.report=result;c.traceDirty=false;c.loadingReport=false;c.jobError='';
          if(active(id,c,token)){restoreUI();$('#report-status').textContent='评分、追踪与证据核验已完成。';toast('可信研判报告已就绪');}return;
        }
        if(['failed','interrupted'].includes(job.status))throw new Error(typeof job.error==='string'?job.error:job.error?.detail||job.error?.message||job.message||'任务未完成，请重试。');
        if(active(id,c,token))renderJob(c);
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }catch(error){
      if(c.job?.job_id===jobId&&c.epoch===token){c.loadingReport=false;c.job={...c.job,status:'failed',stage:'failed'};c.jobError=error.message;if(active(id,c,token)){renderJob(c);$('#report-empty').hidden=false;buttons();}}
    }finally{polling.delete(key);}
  }
  const sameVersions=(a,b)=>!!a&&!!b&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(key=>a[key]===b[key]);
  function targetsAnalysis(address,c,id){
    const canonical=c.analysis?.address_id;if(!canonical)return false;
    const normalize=value=>id==='ethereum'?String(value).trim().toLowerCase():String(value).trim();
    return normalize(address)===normalize(canonical)||(/^\d+$/.test(address)&&Number(address)===c.analysis.analysis?.node_idx);
  }
  $('#report-address-form').addEventListener('submit',async event=>{
    event.preventDefault();const address=$('#report-address-input').value.trim(),id=state.datasetId,c=datasetContext(id);
    if(!address){$('#report-address-error').textContent='请输入当前数据集中的地址或节点 ID。';return;}
    if(c.loadingReport||c.loadingAddress||c.loadingTrace)return;
    const params=traceParameters(),mode=$('#trace-mode').value;
    const same=targetsAnalysis(address,c,id),analysisValid=same&&sameVersions(c.analysis.versions,c.meta?.versions);
    const traceValid=analysisValid&&!c.traceDirty&&c.trace?.analysis_id===c.analysis.analysis_id&&sameVersions(c.trace.versions,c.meta?.versions);
    const body={address,mode:c.reportMode,trace_mode:mode,trace_params:params};
    if(analysisValid)body.reuse_analysis_id=c.analysis.analysis_id;
    if(traceValid)body.reuse_trace_id=c.trace.trace_id;
    const token=++c.epoch;++c.traceEpoch;c.reportDraft=address;c.reportDraftDirty=true;c.report=null;c.loadingReport=true;c.job=null;c.jobError='';
    resetReport();$('#report-cross-links').hidden=true;$('#report-empty').hidden=true;$('#report-address-error').textContent='';
    $('#report-status').textContent='正在校验输入地址与可复用的分析结果…';buttons();
    try{
      let job;
      try{job=await request('/reports/from-address',{datasetId:id,body});}
      catch(error){
        if(error.status!==409||(!body.reuse_analysis_id&&!body.reuse_trace_id))throw error;
        // A release may have changed while this page was open. Rebuild its steps once.
        delete body.reuse_analysis_id;delete body.reuse_trace_id;
        await connect(id);if(c.epoch!==token)return;
        job=await request('/reports/from-address',{datasetId:id,body});
      }
      if(c.epoch!==token)return;c.job={...job,clientEpoch:token};
      if(active(id,c,token)){renderJob(c);buttons();pollJob(id,job.job_id,token);}
    }catch(error){if(c.epoch===token){c.loadingReport=false;c.jobError=error.message;if(active(id,c,token)){$('#report-address-error').textContent=error.message;$('#report-status').textContent='本次报告未生成。';$('#report-empty').hidden=false;buttons();}}}
  });
  $('#evidence-select').addEventListener('change',()=>{state.evidenceLabel=$('#evidence-select').value;selectEvidence(state.evidenceLabel);});
  $('#return-statement').addEventListener('click',returnToStatement);
  $('#fault-button').addEventListener('click',async()=>{
    if(!state.report)return;const id=state.datasetId,c=datasetContext(id),token=c.epoch,reportId=c.report.report_id;
    busy($('#fault-button'),true,'正在运行模拟核验…');
    try{const result=await request(`/reports/${reportId}/demo`,{datasetId:id,body:{kind:$('#fault-kind').value}});if(active(id,c,token)&&reportId===c.report?.report_id)renderFault(result);}
    catch(error){if(active(id,c,token))$('#fault-result').textContent=error.message;}
    finally{if(state.datasetId===id)busy($('#fault-button'),false,'运行核验演示');}
  });
  buttons();contexts();
  try{const registry=await request('/datasets');state.datasets=registry.datasets;$('#dataset-select').innerHTML=state.datasets.map(x=>`<option value="${escape(x.dataset_id)}">${escape(x.label||datasetLabel(x.dataset_id))}${x.ready===false?' · 准备中':''}</option>`).join('');$('#dataset-select').value=state.datasetId;}catch{ /* Meta errors provide the actionable service status below. */ }
  await connect();
}
