import { state } from './state.js';

export function datasetPath(path, id = state.datasetId) {
  const url = new URL(path, location.origin);
  if (url.pathname !== '/datasets' && !url.searchParams.has('dataset_id')) url.searchParams.set('dataset_id', id);
  return url.pathname + url.search;
}
export function downloadPath(path, id = state.datasetId) { return '/api' + datasetPath(path, id); }

export async function request(path, {
  body,
  signal,
  timeout = 190000,
  datasetId = state.datasetId
} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {
    once: true
  });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch('/api' + datasetPath(path, datasetId), {
      method: body ? 'POST' : 'GET',
      headers: body ? {
        'Content-Type': 'application/json'
      } : {},
      body: body ? JSON.stringify(['/reports', '/traces', '/reports/from-address'].includes(path) ? { dataset_id: datasetId, ...body } : body) : undefined,
      signal: controller.signal
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入后重试');
      error.code = data.code; error.status = response.status; error.datasetId = datasetId;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求等待已结束；服务器可能仍在计算，请稍后重试。');
    if (error instanceof TypeError) throw new Error('无法连接分析服务，请检查启动终端后重试。');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
