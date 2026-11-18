import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ProductOperationsPage, { diagnosisScene } from './ProductOperationsPage';

const mocks = vi.hoisted(() => ({ operations: vi.fn(), exportOperations: vi.fn(), copyWithFeedback: vi.fn(), downloadBlobWithFeedback: vi.fn() }));
vi.mock('./api', () => ({ api: mocks }));
vi.mock('./feedback', () => ({ ...mocks, feedbackMessage: { error: vi.fn() } }));
vi.mock('./SkuImagePreview', () => ({ default: () => <span>商品图</span> }));
vi.mock('./components/SkuDetailsDrawer', () => ({ default: ({ sku, onClose }: { sku: string | null; onClose: () => void }) => sku ? <div role="dialog">{sku}详情<button onClick={onClose}>关闭详情</button></div> : null }));
const payload = (sku = 'SKU-ONE', revision = 'v1') => ({ rows: [{ sku, product_name: '中文品名', asins: ['A'], developer: '甲', stock: 100, units_90: 0, scope_capital: 10000, scope_stock: 20, worst_margin: .05, is_aged: true, is_low_margin: true, is_low_sales_new: true, launch_days: 6 }], total: 1, page: 1, page_size: 50, scene: 'clearance', revision, summary: { sku_count: 1, scope_capital: 10000, scope_stock: 20, stock: 100, zero_sales: 1 }, developers: ['甲', '乙'], sources: { operational_sales: { available: true } }, excluded_clearance_rows: 0, missing_launch_count: 0 });
afterEach(() => { cleanup(); mocks.operations.mockReset(); mocks.exportOperations.mockReset(); vi.clearAllMocks(); window.history.replaceState({}, '', '/'); });

describe('ProductOperationsPage', () => {
  it('shows replenishment metrics and sorts using raw server fields', async () => {
    const data = payload();
    mocks.operations.mockResolvedValue({ ...data, rows: [{ ...data.rows[0], clearance_daily_units: 6.7, clearance_total_stock: 41, clearance_available_days: 41 / 6.7 }] });
    render(<ProductOperationsPage />); await screen.findByText('6.12天');
    expect(screen.getByText('6.7', { selector: '.ops-numeric' })).toBeTruthy();
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('columnheader', { name: /日均销量/ }));
    await waitFor(() => expect(mocks.operations).toHaveBeenLastCalledWith(expect.objectContaining({ sort_by: 'clearance_daily_units', sort_order: 'asc', page: 1 }), expect.any(AbortSignal)));
    expect(screen.getByRole('button', { name: /复制所选SKU/ })).toBeDisabled();
    fireEvent.focus(screen.getByText('6.12天'));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('总库存 41 件');
  });
  it('keeps zero distinct from missing and does not round a small positive daily rate to zero', async () => {
    const data = payload();
    mocks.operations.mockResolvedValue({ ...data, total: 3, rows: [
      { ...data.rows[0], sku: 'ZERO', clearance_daily_units: 0, clearance_total_stock: 41, clearance_available_days: null },
      { ...data.rows[0], sku: 'MISSING', clearance_daily_units: null, clearance_total_stock: null, clearance_available_days: null },
      { ...data.rows[0], sku: 'SMALL', clearance_daily_units: 1 / 3000, clearance_total_stock: 41, clearance_available_days: 123000 },
    ] });
    render(<ProductOperationsPage />); await screen.findByText('＜0.01');
    const zero = screen.getByText('ZERO').closest('tr')!;
    expect(within(zero).getByText('0', { selector: '.ops-numeric' })).toBeTruthy();
    expect(within(zero).getByText('—', { selector: '.ops-numeric' })).toBeTruthy();
    expect(within(screen.getByText('MISSING').closest('tr')!).getAllByText('—', { selector: '.ops-numeric' })).toHaveLength(2);
    expect(screen.getByText('123,000天')).toBeTruthy();
  });
  it('keeps drafts out of queries and clears selection when applied scope changes', async () => {
    mocks.operations.mockResolvedValue(payload());
    render(<ProductOperationsPage />);
    await screen.findByText('SKU-ONE');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    expect(screen.getByText('已选 1 个SKU')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('搜索品名 / SKU / ASIN'), { target: { value: 'DRAFT' } });
    expect(mocks.operations).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByPlaceholderText('搜索品名 / SKU / ASIN'), { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(mocks.operations).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'DRAFT', page: 1 }), expect.any(AbortSignal)));
    expect(screen.getByRole('button', { name: /复制所选SKU/ })).toBeDisabled();
  });
  it('copies and exports the same selected SKU scope and preserves the queue after detail closes', async () => {
    mocks.operations.mockResolvedValue(payload()); mocks.exportOperations.mockResolvedValue(new Blob(['CSV']));
    render(<ProductOperationsPage />); await screen.findByText('SKU-ONE');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: /复制所选SKU/ }));
    expect(mocks.copyWithFeedback).toHaveBeenCalledWith('SKU-ONE', '所选SKU', 1);
    fireEvent.click(screen.getByRole('button', { name: /导出所选清单/ }));
    await waitFor(() => expect(mocks.exportOperations).toHaveBeenCalledWith(expect.objectContaining({ scene: 'clearance' }), ['SKU-ONE']));
    fireEvent.click(screen.getByRole('button', { name: '中文品名' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('SKU-ONE详情');
    fireEvent.click(screen.getByText('关闭详情')); expect(screen.getByText('已选 1 个SKU')).toBeTruthy();
  });
  it('clears old selections on a data revision change', async () => {
    mocks.operations.mockResolvedValueOnce(payload()).mockResolvedValue(payload('SKU-ONE', 'v2'));
    const { rerender } = render(<ProductOperationsPage />); await screen.findByText('SKU-ONE');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    rerender(<ProductOperationsPage refreshVersion={1} />);
    await waitFor(() => expect(screen.getByRole('button', { name: /复制所选SKU/ })).toBeDisabled());
  });
  it('switches to the new-product queue without old scene data or a stale response', async () => {
    let finish!: (value: ReturnType<typeof payload>) => void;
    mocks.operations.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(payload('NEW'));
    render(<ProductOperationsPage />);
    fireEvent.click(screen.getByRole('tab', { name: '新品低销' }));
    await screen.findByText('NEW');
    await act(async () => finish(payload('STALE')));
    expect(screen.queryByText('STALE')).toBeNull();
    expect(mocks.operations).toHaveBeenLastCalledWith(expect.objectContaining({ scene: 'new', new_mode: 'low' }), expect.any(AbortSignal));
  });
  it('does not request inactive pages and resolves old bookmarks', () => {
    render(<ProductOperationsPage active={false} />); expect(mocks.operations).not.toHaveBeenCalled();
    expect(diagnosisScene('?page=new-products')).toBe('new');
    expect(diagnosisScene('?page=products&tab=low-margin')).toBe('margin');
  });
});
