export function apiErrorMessage(payload: unknown, fallback = '请求失败') {
  const response = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const detail = response.detail ?? payload;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const structured = detail as Record<string, unknown>;
    const message = typeof structured.message === 'string' && structured.message ? structured.message : fallback;
    const count = Number.isFinite(Number(structured.count)) ? `（${Number(structured.count)} 条）` : '';
    const examples = Array.isArray(structured.examples) && structured.examples.length
      ? `；示例：${structured.examples.slice(0, 3).map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('、')}`
      : '';
    return `${message}${count}${examples}`;
  }
  return fallback;
}
