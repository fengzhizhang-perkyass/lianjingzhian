// Input text is a draft. Only successful lookups replace the active analysis.
export const state = {
  page: 'landing',
  module: 'queue',
  lastModule: 'queue',
  hasWorkspace: false,
  meta: null,
  analysis: null,
  trace: null,
  report: null,
  epoch: 0,
  traceEpoch: 0,
  traceDirty: false,
  loadingAddress: false,
  loadingTrace: false,
  loadingReport: false
};
export function newContext() {
  state.epoch++;
  state.traceEpoch++;
  state.analysis = null;
  state.trace = null;
  state.report = null;
  state.traceDirty = false;
  state.loadingTrace = false;
  state.loadingReport = false;
  return state.epoch;
}
