import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SkuDetailsDrawer, { ObservationChart } from './SkuDetailsDrawer';
const mocks = vi.hoisted(() => ({ operationsDetail: vi.fn(), operationsSeries: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../SkuImagePreview', () => ({ default: () => <span>商品图</span> }));
const detail = (sku: string) => ({ identity: { sku, product_name: '中文品名', developer: '甲', asins: ['A', 'B'] }, markets: [{ asin: 'A', country: 'DE' }, { asin: 'B', country: 'FR' }], aging: [], records: [], sources: {}, revision: 'v1' });
afterEach(() => { cleanup(); mocks.operationsDetail.mockReset(); mocks.operationsSeries.mockReset(); vi.clearAllMocks(); });
describe('SkuDetailsDrawer', () => {
  it('shows real zero SKU window totals with their operational source and grain', async () => {
    mocks.operationsDetail.mockResolvedValue({ ...detail('SKU'), identity: { ...detail('SKU').identity, units_7: 0, units_30: 0 }, sources: { operational_sales: { available: true, uploaded_at: '2026-11-17 09:45:43' } } });
    render(<SkuDetailsDrawer sku="SKU" onClose={vi.fn()} />);
    await screen.findByText('SKU汇总销量参考');
    expect(screen.getAllByText('0 单')).toHaveLength(2);
    expect(screen.getByText(/为SKU跨国汇总/)).toHaveTextContent('2026-11-17 09:45:43');
  });
  it('loads exact selected market history only when the history tab is opened', async () => {
    mocks.operationsDetail.mockResolvedValue(detail('SKU')); mocks.operationsSeries.mockResolvedValue({ rows: [], events: [], sales_as_of: '2026-11-16' });
    render(<SkuDetailsDrawer sku="SKU" initialAsin="B" initialCountry="FR" onClose={vi.fn()} />);
    await screen.findByText('中文品名'); expect(mocks.operationsSeries).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('tab', { name: '趋势与历史' }));
    await waitFor(() => expect(mocks.operationsSeries).toHaveBeenLastCalledWith('SKU', { asin: 'B', country: 'FR', days: 30 }, expect.any(AbortSignal)));
    fireEvent.click(screen.getByText('90天'));
    await waitFor(() => expect(mocks.operationsSeries).toHaveBeenLastCalledWith('SKU', { asin: 'B', country: 'FR', days: 90 }, expect.any(AbortSignal)));
  });
  it('does not leak a previous SKU response into a newly opened detail', async () => {
    let finish!: (value: ReturnType<typeof detail>) => void;
    mocks.operationsDetail.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(detail('NEW'));
    const { rerender } = render(<SkuDetailsDrawer sku="OLD" onClose={vi.fn()} />);
    rerender(<SkuDetailsDrawer sku="NEW" onClose={vi.fn()} />); await screen.findByText('NEW');
    await act(async () => finish(detail('OLD'))); expect(screen.queryByText('OLD')).toBeNull();
  });
  it('renders separate path segments across unknown dates and keeps real zero points', () => {
    const { container } = render(<ObservationChart field="units" title="每日销量" rows={[{ date: '2026-11-01', units: 0, price: null, event: false }, { date: '2026-11-02', units: null, price: null, event: false }, { date: '2026-11-03', units: 5, price: null, event: false }]} />);
    expect(container.querySelector('.ops-chart-line')?.getAttribute('d')?.match(/M/g)).toHaveLength(2);
    expect(container.querySelectorAll('circle')).toHaveLength(2);
  });
  it('presents manual history with business labels and keeps internal identifiers out of the expanded record', async () => {
    mocks.operationsDetail.mockResolvedValue({ ...detail('SKU'), records: [{ id: 'INTERNAL-ID', batch_id: 'INTERNAL-BATCH', kind: '长期调价', batch_name: '十一月清仓', effective_date: '2026-11-01', discount_percent: 10 }] });
    mocks.operationsSeries.mockResolvedValue({ rows: [], events: [], sales_as_of: '2026-11-16' });
    render(<SkuDetailsDrawer sku="SKU" onClose={vi.fn()} />); await screen.findByText('中文品名');
    fireEvent.click(screen.getByRole('tab', { name: '趋势与历史' })); await screen.findByText('十一月清仓');
    fireEvent.click(screen.getByRole('button', { name: /Expand row|展开行/ }));
    expect(screen.getByText('调价批次')).toBeTruthy();
    expect(screen.queryByText('INTERNAL-BATCH')).toBeNull();
  });
});
