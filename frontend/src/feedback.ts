import { message as antdMessage } from 'antd';

export type OperationFeedbackOptions<T> = {
  key: string;
  loading?: string;
  success?: string | ((result: T) => string);
  warning?: string | ((result: T) => string);
  error?: string | ((reason: unknown) => string);
  warningWhen?: (result: T) => boolean;
};

export const feedbackMessage = antdMessage;

export function configureFeedback() {
  antdMessage.config({ top: 24, maxCount: 3, duration: 2.5 });
}

export const feedbackError = (reason: unknown, fallback = '操作失败') => reason instanceof Error && reason.message ? reason.message : fallback;

export function isAbortError(reason: unknown) {
  return (typeof DOMException !== 'undefined' && reason instanceof DOMException && reason.name === 'AbortError')
    || (reason instanceof Error && reason.name === 'AbortError');
}

function messageText<T>(value: string | ((value: T) => string) | undefined, data: T, fallback: string) {
  if (typeof value === 'function') return value(data);
  return value || fallback;
}

export async function runOperation<T>(operation: () => Promise<T>, options: OperationFeedbackOptions<T>) {
  if (options.loading) feedbackMessage.loading({ key: options.key, content: options.loading, duration: 0 });
  try {
    const result = await operation();
    const hasWarning = Boolean(options.warningWhen?.(result));
    if (hasWarning && options.warning) {
      feedbackMessage.warning({ key: options.key, content: messageText(options.warning, result, '操作完成，但有部分结果需要注意'), duration: 6 });
    } else if (options.success) {
      feedbackMessage.success({ key: options.key, content: messageText(options.success, result, '操作已完成'), duration: 2.5 });
    } else if (options.warning) {
      feedbackMessage.warning({ key: options.key, content: messageText(options.warning, result, '操作完成，但有部分结果需要注意'), duration: 6 });
    }
    return result;
  } catch (reason) {
    if (!isAbortError(reason)) feedbackMessage.error({ key: options.key, content: messageText(options.error, reason, feedbackError(reason)), duration: 6 });
    throw reason;
  }
}

export async function writeClipboardText(text: string) {
  if (!text.trim()) throw new Error('没有可复制的内容');
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Continue with the legacy synchronous fallback for older browsers and embedded views.
    }
  }
  const input = document.createElement('textarea');
  input.value = text;
  input.readOnly = true;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('剪贴板写入失败，请检查浏览器权限后重试');
}

export async function copyWithFeedback(text: string, label: string, count?: number) {
  const key = `copy-${label}`;
  if (!text.trim()) {
    feedbackMessage.info({ key, content: `暂无${label}可复制`, duration: 3 });
    return false;
  }
  try {
    await writeClipboardText(text);
    feedbackMessage.success({ key, content: `已复制${count === undefined ? '' : ` ${count} 个`}${label}`, duration: 2.5 });
    return true;
  } catch (reason) {
    feedbackMessage.error({ key, content: feedbackError(reason, `复制${label}失败，请重试`), duration: 6 });
    return false;
  }
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

function responseFilename(response: Response, fallback: string) {
  const header = response.headers.get('Content-Disposition') || '';
  const encoded = header.match(/filename\*=(?:UTF-8'')?([^;]+)/i)?.[1];
  const plain = header.match(/filename="?([^";]+)"?/i)?.[1];
  const candidate = encoded || plain;
  if (!candidate) return fallback;
  try { return decodeURIComponent(candidate.trim()); } catch { return candidate.trim(); }
}

export function downloadBlobWithFeedback(blob: Blob, filename: string, label = filename) {
  try {
    triggerBlobDownload(blob, filename);
    feedbackMessage.success({ content: `${label}已生成并开始下载`, duration: 2.5 });
    return true;
  } catch (reason) {
    feedbackMessage.error({ content: feedbackError(reason, `${label}下载失败，请重试`), duration: 6 });
    return false;
  }
}

export async function downloadWithFeedback(url: string, fallbackFilename: string, label = fallbackFilename) {
  const key = `download-${url}`;
  feedbackMessage.loading({ key, content: `正在生成${label}…`, duration: 0 });
  try {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) {
      const payload = await response.clone().json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
      const detail = typeof payload?.detail === 'string' ? payload.detail : typeof payload?.message === 'string' ? payload.message : `请求失败（${response.status}）`;
      throw new Error(detail);
    }
    triggerBlobDownload(await response.blob(), responseFilename(response, fallbackFilename));
    feedbackMessage.success({ key, content: `${label}已生成并开始下载`, duration: 2.5 });
    return true;
  } catch (reason) {
    if (!isAbortError(reason)) feedbackMessage.error({ key, content: feedbackError(reason, `${label}下载失败，请重试`), duration: 6 });
    return false;
  }
}
