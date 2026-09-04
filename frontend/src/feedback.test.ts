import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { feedbackMessage, runOperation, copyWithFeedback, downloadWithFeedback, isAbortError } from './feedback';

function stubMessage(method: 'loading' | 'success' | 'warning' | 'error' | 'info') {
  return vi.spyOn(feedbackMessage, method).mockImplementation(() => undefined as never);
}

describe('feedback helpers', () => {
  beforeEach(() => {
    (['loading', 'success', 'warning', 'error', 'info'] as const).forEach(stubMessage);
  });
  afterEach(() => vi.restoreAllMocks());

  it('replaces keyed loading with success and warning results', async () => {
    const loading = vi.mocked(feedbackMessage.loading);
    const success = vi.mocked(feedbackMessage.success);
    const warning = vi.mocked(feedbackMessage.warning);
    await runOperation(async () => ({ ignored: 0 }), {
      key: 'upload-demo', loading: '正在上传', success: '上传成功', warning: '上传完成但有警告', warningWhen: result => result.ignored > 0,
    });
    await runOperation(async () => ({ ignored: 2 }), {
      key: 'upload-demo', loading: '正在上传', success: '上传成功', warning: result => `忽略 ${result.ignored} 项`, warningWhen: result => result.ignored > 0,
    });
    expect(loading).toHaveBeenCalledTimes(2);
    expect(success).toHaveBeenCalledWith(expect.objectContaining({ key: 'upload-demo' }));
    expect(warning).toHaveBeenCalledWith(expect.objectContaining({ key: 'upload-demo' }));
  });

  it('does not show an error toast for AbortError', async () => {
    const reason = new Error('cancelled'); reason.name = 'AbortError';
    expect(isAbortError(reason)).toBe(true);
    await expect(runOperation(() => Promise.reject(reason), { key: 'abort-test', error: '请求失败' })).rejects.toBe(reason);
    expect(feedbackMessage.error).not.toHaveBeenCalled();
  });

  it('copies with the standard API and falls back to execCommand', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    await expect(copyWithFeedback('A\nB', 'SKU', 2)).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('A\nB');
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn().mockReturnValue(true) });
    await expect(copyWithFeedback('C', 'SKU', 1)).resolves.toBe(true);
    expect(document.execCommand).toHaveBeenCalledWith('copy');
  });

  it('reports empty clipboard lists and permission failures', async () => {
    await expect(copyWithFeedback('  ', 'SKU')).resolves.toBe(false);
    expect(feedbackMessage.info).toHaveBeenCalled();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn().mockReturnValue(false) });
    await expect(copyWithFeedback('SKU-1', 'SKU', 1)).resolves.toBe(false);
    expect(feedbackMessage.error).toHaveBeenCalled();
  });

  it('downloads only successful responses and cleans the blob URL', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const response = {
      ok: true, status: 200,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="report.csv"' }),
      blob: vi.fn().mockResolvedValue(new Blob(['csv'])), clone() { return this; },
    } as unknown as Response;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
    await expect(downloadWithFeedback('/api/report', 'fallback.csv', '业绩报表')).resolves.toBe(true);
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test');
    expect(click).toHaveBeenCalled();
    const failed = { ok: false, status: 500, clone: () => ({ json: () => Promise.resolve({ detail: '服务器错误' }) }) } as unknown as Response;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failed));
    await expect(downloadWithFeedback('/api/report', 'fallback.csv', '业绩报表')).resolves.toBe(false);
    expect(feedbackMessage.error).toHaveBeenCalled();
  });
});
