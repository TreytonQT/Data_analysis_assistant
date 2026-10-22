import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import NewProductMonitorPage from './NewProductMonitorPage';

const apiMocks = vi.hoisted(() => ({ newProductView: vi.fn() }));
vi.mock('./api', () => ({ api: apiMocks }));
vi.mock('./feedback', () => ({
  copyWithFeedback: vi.fn(async (text: string) => {
    await navigator.clipboard.writeText(text);
    return true;
  }),
  downloadWithFeedback: vi.fn(),
}));

const raiseSkus = Array.from({ length: 55 }, (_, index) => 'RAISE-' + index);
const makeView = () => ({
  title: '新品监控',
  has_data: true,
  filters: { developers: ['甲', '乙'] },
  selected: {},
  metrics: [
    { name: '新品 SKU 数', value: 2 },
    { name: '建议涨价', value: 1 },
    { name: '建议降价', value: 1 },
    { name: '可售数量合计', value: 30 },
    { name: '近30天销量', value: 20 },
    { name: '已断货', value: 0 },
    { name: '新品观察中', value: 0 },
    { name: '数据异常', value: 0 },
  ],
  sections: [{
    key: 'detail', title: '新品监控明细', columns: [],
    rows: [
      { SKU: 'RAISE-1', ASIN: 'A1', 监控状态: '建议涨价', 可售数量: 4, 日均销量: 1, 可售覆盖天数: 4 },
      { SKU: 'LOWER-1', ASIN: 'A2', 监控状态: '建议降价', 可售数量: 100, 日均销量: 1, 可售覆盖天数: 100 },
    ],
    page: 1, page_size: 50, total: 2, paginated: false, server_managed: true,
  }],
  copy_lists: { raise_skus: raiseSkus, lower_skus: ['LOWER-1'], calculation_date: '2026-10-13' },
  calculation_date: '2026-10-13',
  source_uploaded_at: '2026-10-12T09:00:00+08:00',
  excluded_invalid_launch_count: 0,
});

describe('NewProductMonitorPage', () => {
  afterEach(() => {
    cleanup();
    apiMocks.newProductView.mockReset();
    vi.clearAllMocks();
  });

  it('loads one snapshot and copies the full list beyond the table page', async () => {
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboardWrite } });
    apiMocks.newProductView.mockResolvedValue(makeView());
    render(<NewProductMonitorPage />);
    expect(await screen.findByText('建议涨价 SKU（55）')).toBeTruthy();
    expect(screen.getByText('建议降价 SKU（1）')).toBeTruthy();
    expect(apiMocks.newProductView).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '复制涨价 SKU' }));
    await waitFor(() => expect(clipboardWrite).toHaveBeenCalledWith(raiseSkus.join('\n')));
  });

  it('uses one new request for a search change', async () => {
    apiMocks.newProductView.mockResolvedValue(makeView());
    render(<NewProductMonitorPage />);
    await screen.findByText('RAISE-1');
    const search = screen.getByPlaceholderText('搜索 SKU 或 ASIN');
    fireEvent.change(search, { target: { value: 'A1' } });
    expect(apiMocks.newProductView).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(apiMocks.newProductView).toHaveBeenLastCalledWith(
      expect.objectContaining({ launch_stage: 'all', status: 'all', search: 'A1', page: '1' }),
      expect.any(AbortSignal),
    ));
    expect(apiMocks.newProductView).toHaveBeenCalledTimes(2);
  });

  it('uses one new request for a developer change', async () => {
    apiMocks.newProductView.mockResolvedValue(makeView());
    render(<NewProductMonitorPage />);
    await screen.findByText('RAISE-1');
    fireEvent.click(screen.getByRole('button', { name: '开发员: 全部开发员' }));
    fireEvent.change(screen.getByRole('textbox', { name: '搜索开发员' }), { target: { value: '甲' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '全选当前搜索结果' }));
    expect(apiMocks.newProductView).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '确定' }));
    await waitFor(() => expect(apiMocks.newProductView).toHaveBeenLastCalledWith(
      expect.objectContaining({ developers: '甲', page: '1' }), expect.any(AbortSignal),
    ));
    expect(apiMocks.newProductView).toHaveBeenCalledTimes(2);
  });

  it('keeps missing daily average blank while showing infinity for zero sales', async () => {
    const view = makeView();
    const rows = [
      { SKU: 'ZERO-SALES', ASIN: 'A3', 监控状态: '新品观察中', 可售数量: 10, 日均销量: 0, 可售覆盖天数: null },
      { SKU: 'MISSING-AVG', ASIN: 'A4', 监控状态: '数据异常', 可售数量: 10, 日均销量: null, 可售覆盖天数: null },
    ];
    apiMocks.newProductView.mockResolvedValue({ ...view, sections: [{ ...view.sections[0], rows }] });
    render(<NewProductMonitorPage />);
    expect(await screen.findByText('MISSING-AVG')).toBeTruthy();
    expect(screen.getAllByText('∞')).toHaveLength(1);
  });

  it('ignores an older response after a rapid filter change', async () => {
    let finishFirst!: (value: ReturnType<typeof makeView>) => void;
    const current = makeView();
    current.sections[0].rows[0].SKU = 'CURRENT-SKU';
    current.copy_lists.raise_skus = ['CURRENT-SKU'];
    apiMocks.newProductView
      .mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve; }))
      .mockResolvedValueOnce(current);
    render(<NewProductMonitorPage />);
    await waitFor(() => expect(apiMocks.newProductView).toHaveBeenCalledTimes(1));
    const search = screen.getByPlaceholderText('搜索 SKU 或 ASIN');
    fireEvent.change(search, { target: { value: 'CURRENT' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await screen.findByText('CURRENT-SKU');
    expect(apiMocks.newProductView.mock.calls[0][1].aborted).toBe(true);
    const old = makeView();
    old.sections[0].rows[0].SKU = 'OLD-SKU';
    await act(async () => { finishFirst(old); });
    expect(screen.queryByText('OLD-SKU')).toBeNull();
    expect(screen.getByText('CURRENT-SKU')).toBeTruthy();
    expect(screen.getByText('建议涨价 SKU（1）')).toBeTruthy();
  });
});
