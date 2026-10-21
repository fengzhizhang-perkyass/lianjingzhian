export async function request(path, {
  body,
  signal,
  timeout = 190000
} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {
    once: true
  });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch('/api' + path, {
      method: body ? 'POST' : 'GET',
      headers: body ? {
        'Content-Type': 'application/json'
      } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入后重试');
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
