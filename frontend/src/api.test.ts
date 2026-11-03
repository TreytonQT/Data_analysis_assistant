import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, apiErrorMessage } from './api';
import { formatAmountInWan } from './formatters';
import { marginBand, ratingBand } from './productPresentation';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('shared API transport', () => {
  it('preserves multipart field names and upload warnings', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ warnings: ['部分图片缺失'] }) });
    vi.stubGlobal('fetch', fetch);
    const first = new File(['a'], 'a.csv');
    const second = new File(['b'], 'b.csv');
    expect(await api.uploadReports('/api/reports/performance', [first, second], true)).toEqual({ warnings: ['部分图片缺失'] });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/reports/performance');
    expect(init.method).toBe('POST');
    expect(init.body.getAll('files').map((file: File) => file.name)).toEqual(['a.csv', 'b.csv']);
    expect(init.body.has('file')).toBe(false);
    expect(init.headers).toBeUndefined();
    await api.uploadConfig('store_config', first);
    expect(fetch.mock.calls[1][0]).toBe('/api/config/store_config/upload');
    expect(fetch.mock.calls[1][1].body.get('file').name).toBe('a.csv');
  });

  it('keeps structured validation detail across uploads and downloads', async () => {
    const detail = { detail: { message: '字段不合法', count: 2, examples: ['A', 'B'] } };
    const expected = '字段不合法（2 条）；示例：A、B';
    expect(apiErrorMessage(detail)).toBe(expected);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => detail }));
    await expect(api.uploadReports('/api/reports/source/rating', [new File(['x'], 'x.xlsx')], false)).rejects.toThrow(expected);
  });
});

describe('display compatibility', () => {
  it('preserves amount scale and exact existing risk boundaries', () => {
    expect(formatAmountInWan(12345)).toBe('1.23');
    expect(formatAmountInWan(0)).toBe('0.00');
    expect(formatAmountInWan(-10000)).toBe('-1.00');
    expect([-0.01, 0, 0.099, 0.1, 0.199, 0.2].map(marginBand)).toEqual(['negative', 'low', 'low', 'warning', 'warning', 'good']);
    expect([3.49, 3.5, 4.29, 4.3].map(ratingBand)).toEqual(['danger', 'warning', 'warning', 'good']);
  });
});
