import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import PriceTrackingPage from './PriceTrackingPage';
const mocks = vi.hoisted(() => ({ tracking: vi.fn(), downloadWithFeedback: vi.fn() }));
vi.mock('./api', () => ({ api: mocks }));
vi.mock('./feedback', () => mocks);
vi.mock('./SkuImagePreview', () => ({ default: () => <span>商品图</span> }));
vi.mock('./components/SkuDetailsDrawer', () => ({ default: () => null }));
const payload = (sku = 'SKU-DE') => ({ rows: [{ sku, product_name: '产品名称', asin: 'A', country: 'DE', developer: '甲', currency: 'EUR', date: '2026-11-15', old_effective_price: 100, new_effective_price: 105, change: .05, band: 5, units_7: 14, units_30: 30, t_value: 1 }], total: 1, distribution_total: 1, buckets: [{ band: 5, count: 1, mean_t: 1, up: 1, down: 0, flat: 0, missing: 0 }], metrics: { sku_count: 1, records: 1 }, as_of: '2026-11-16', coverage: { start: '2026-11-01', end: '2026-11-17' }, developers: ['甲'], sources: {}, warnings: [] });
afterEach(() => { cleanup(); mocks.tracking.mockReset(); vi.clearAllMocks(); window.history.replaceState({}, '', '/'); });
describe('PriceTrackingPage', () => {
  it('shows operational SKU totals as separate references without replacing missing country T', async () => {
    const data = payload();
    mocks.tracking.mockResolvedValue({ ...data, rows: [{ ...data.rows[0], units_7: null, units_30: null, t_value: null, sku_units_7: 70, sku_units_30: 300, sku_t_value: 0, sku_sales_source: '运营原始表（SKU跨国汇总）' }], metrics: { sku_count: 1, records: 1, missing: 1, sku_reference: 1 } });
    render(<PriceTrackingPage />); await screen.findByText(/SKU总量 70 \/ 300/);
    expect(screen.getByText('站点证据缺失')).toBeTruthy();
    expect(screen.getByText('SKU参考T 0')).toBeTruthy();
    expect(screen.getByText(/不计入站点排名或分布统计/)).toBeTruthy();
  });
  it('uses absolute T ranking and clickable distribution without submitting a search draft', async () => {
    mocks.tracking.mockResolvedValue(payload()); render(<PriceTrackingPage />); await screen.findByText(/SKU-DE/);
    expect(mocks.tracking).toHaveBeenLastCalledWith(expect.objectContaining({ direction: 'up', sort_by: 'abs_t' }), expect.any(AbortSignal));
    fireEvent.change(screen.getByPlaceholderText('品名 / SKU / ASIN'), { target: { value: 'DRAFT' } });
    fireEvent.click(screen.getByRole('button', { name: /5–10%/ }));
    await waitFor(() => expect(mocks.tracking).toHaveBeenLastCalledWith(expect.objectContaining({ search: '', band: 5 }), expect.any(AbortSignal)));
    expect(screen.getByRole('button', { name: /5–10%/ })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: /导出/ }));
    expect(mocks.downloadWithFeedback).toHaveBeenCalledWith(expect.stringContaining('band=5'), 'price-tracking-up.csv', '站点追踪清单');
    expect(screen.getByText(/涉及SKU/)).toHaveTextContent('站点记录');
  });
  it('clears the prior direction while the next route is loading', async () => {
    mocks.tracking.mockResolvedValueOnce(payload('UP')).mockImplementationOnce(() => new Promise(() => {}));
    const { rerender } = render(<PriceTrackingPage />); await screen.findByTitle('UP');
    window.history.replaceState({}, '', '/?page=price-monitor&direction=down');
    rerender(<PriceTrackingPage routeVersion={1} />);
    await screen.findByRole('heading', { name: '降价追踪' });
    expect(screen.queryByTitle('UP')).toBeNull();
    await waitFor(() => expect(mocks.tracking).toHaveBeenLastCalledWith(expect.objectContaining({ direction: 'down', band: undefined }), expect.any(AbortSignal)));
  });
  it('rejects late responses and pauses inactive requests', async () => {
    let finish!: (value: ReturnType<typeof payload>) => void;
    mocks.tracking.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(payload('NEW'));
    const { rerender } = render(<PriceTrackingPage active={false} />); expect(mocks.tracking).not.toHaveBeenCalled();
    rerender(<PriceTrackingPage />);
    fireEvent.change(screen.getByPlaceholderText('品名 / SKU / ASIN'), { target: { value: 'NEW' } });
    fireEvent.keyDown(screen.getByPlaceholderText('品名 / SKU / ASIN'), { key: 'Enter', code: 'Enter', keyCode: 13 });
    await screen.findByTitle('NEW'); await act(async () => finish(payload('OLD')));
    expect(screen.queryByTitle('OLD')).toBeNull();
  });
});
