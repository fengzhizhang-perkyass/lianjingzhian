// Dataset contexts are independent; input drafts never replace successful results.
const contexts = new Map();
export const datasetIds = ['bitcoin', 'ethereum'];
export const datasetLabel = id => ({ bitcoin: '比特币', ethereum: '以太坊' }[id] || id);
export function datasetContext(id) {
  if (!datasetIds.includes(id)) throw new Error('请选择有效的数据集。');
  if (!contexts.has(id)) contexts.set(id, {
    meta: null, analysis: null, trace: null, report: null, epoch: 0, traceEpoch: 0,
    traceDirty: false, loadingAddress: false, loadingTrace: false, loadingReport: false,
    addressDraft: '', reportDraft: '', reportDraftDirty: false, reportDraftAddress: null, reportMode: 'auto', traceMode: 'quick', traceForm: null,
    groupViews: new Map(), pathIndex: null, evidenceLabel: null, job: null, jobError: '', lastModule: null,
    queue: { offset: 0, limit: 100, total: 0, result: null, loading: false, sequence: 0 }
  });
  return contexts.get(id);
}
const initial = new URLSearchParams(location.search).get('dataset');
export const state = { page: 'landing', module: 'queue', hasWorkspace: false,
  datasetId: datasetIds.includes(initial) ? initial : 'bitcoin', datasets: [] };
for (const field of Object.keys(datasetContext('bitcoin'))) Object.defineProperty(state, field, {
  get: () => datasetContext(state.datasetId)[field],
  set: value => { datasetContext(state.datasetId)[field] = value; }, enumerable: true
});
export function selectDataset(id) { datasetContext(id); state.datasetId = id; }
export function newContext(id = state.datasetId) {
  const context = datasetContext(id);
  context.epoch++; context.traceEpoch++;
  context.analysis = null; context.trace = null; context.report = null;
  context.traceDirty = false; context.loadingTrace = false; context.loadingReport = false;
  context.pathIndex = null; context.evidenceLabel = null; context.groupViews.clear();
  return context.epoch;
}
