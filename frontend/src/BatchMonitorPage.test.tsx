import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BatchMonitorPage from './BatchMonitorPage';
import type { BatchMonitorDetails, BatchMonitorPayload } from './api';

const apiMocks = vi.hoisted(() => ({
  batchMonitor: vi.fn(),
  batchDetails: vi.fn(),
  batchOrphans: vi.fn(),
  batchCopyLists: vi.fn(),
  createBatch: vi.fn(),
  uploadBatchShipments: vi.fn(),
  updateBatchArtwork: vi.fn(),
  updateShipmentArrival: vi.fn(),
  updateSkuArrival: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMocks,
    },
  };
});

const payload: BatchMonitorPayload = {
  metrics: {
    incomplete_batches: 1,
    pending_artwork_batches: 1,
    pending_shipment_skus: 1,
    pending_arrival_skus: 1,
  },
  rows: [{
    batch_no: 'ABC260701',
    artwork_completed_date: null,
    source_file_name: 'ABC.xlsx',
    created_at: '2026-07-30T10:00:00+08:00',
    updated_at: '2026-07-30T10:00:00+08:00',
    sku_count: 2,
    shipped_count: 1,
    arrived_count: 0,
    shipment_count: 1,
    is_complete: false,
  }],
  page: 1,
  page_size: 20,
  total: 1,
  view: 'incomplete',
  orphan_count: 3,
  orphan_scope_available: true,
  orphan_scope_message: '',
  updated_at: 'revision-1',
};

const details: BatchMonitorDetails = {
  batch: payload.rows[0],
  skus: [
    {
      sku: 'SKU-A01',
      de_price: 5.99,
      fr_price: 6.99,
      es_price: 7.99,
      it_price: 8.99,
      asin: 'B0ABC12345',
      shipment_no: 'FBA-FIRST',
      arrival_date: null,
    },
    {
      sku: 'SKU-A02',
      de_price: null,
      fr_price: null,
      es_price: null,
      it_price: null,
      asin: null,
      shipment_no: null,
      arrival_date: null,
    },
  ],
};

describe('BatchMonitorPage', () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach(mock => mock.mockReset());
    apiMocks.batchMonitor.mockResolvedValue(payload);
    apiMocks.batchDetails.mockResolvedValue(details);
    apiMocks.batchOrphans.mockResolvedValue({ rows: [], page: 1, page_size: 50, total: 0 });
    apiMocks.batchCopyLists.mockResolvedValue({
      unbound_shipment_skus: ['SKU-NO-SHIPMENT-A', 'SKU-NO-SHIPMENT-B'],
      pending_shipment_nos: ['FBA-PENDING-1', 'FBA-PENDING-2'],
      unbound_shipment_count: 2,
      pending_shipment_count: 2,
      updated_at: 'revision-1',
    });
    apiMocks.updateBatchArtwork.mockResolvedValue({
      batch_no: 'ABC260701',
      completed: true,
      artwork_completed_date: '2026-07-30',
    });
    apiMocks.updateSkuArrival.mockResolvedValue({
      sku: 'SKU-A01',
      arrived: true,
      arrival_date: '2026-07-30',
    });
    apiMocks.updateShipmentArrival.mockResolvedValue({
      shipment_no: 'FBA-FIRST',
      arrival_date: '2026-07-30',
      updated: 1,
      total: 1,
      already_arrived: 0,
      affected_batches: [{
        batch_no: 'ABC260701',
        updated_skus: 1,
        arrived_count: 1,
        sku_count: 2,
        is_complete: false,
      }],
    });
    apiMocks.createBatch.mockResolvedValue({
      batch_no: 'NEW260701',
      sheet: 'sheet1',
      sku_count: 2,
      source_sku_count: 3,
      imported_sku_count: 2,
      ignored_sku_count: 1,
      ignored_examples: [{ sku: 'SKU-X01', reason: '运营原始表无记录' }],
    });
  });

  afterEach(() => cleanup());

  it('shows newline-separated copy lists and copies each block as plain text', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    render(<BatchMonitorPage />);

    const unbound = await screen.findByRole('textbox', {
      name: '未绑定货件单号的SKU清单',
    });
    const shipments = screen.getByRole('textbox', {
      name: '未到货货件单号清单',
    });
    expect(unbound).toHaveValue('SKU-NO-SHIPMENT-A\nSKU-NO-SHIPMENT-B');
    expect(shipments).toHaveValue('FBA-PENDING-1\nFBA-PENDING-2');

    await user.click(screen.getByRole('button', {
      name: '复制全部未绑定货件单号的SKU',
    }));
    expect(writeText).toHaveBeenCalledWith('SKU-NO-SHIPMENT-A\nSKU-NO-SHIPMENT-B');
  });

  it('loads incomplete batches by default and expands SKU details lazily', async () => {
    const user = userEvent.setup();
    render(<BatchMonitorPage />);

    await screen.findByText('ABC260701');
    expect(apiMocks.batchMonitor).toHaveBeenCalledWith({
      view: 'incomplete',
      search: '',
      page: 1,
      page_size: 20,
    });
    expect(screen.getByText('已发货')).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '展开ABC260701' }));
    await screen.findByText('SKU-A01');
    expect(apiMocks.batchDetails).toHaveBeenCalledWith('ABC260701');
    expect(screen.getAllByText(/未维护/)).toHaveLength(4);
    expect(screen.queryByText('首次上传')).not.toBeInTheDocument();
  });

  it('updates artwork and SKU arrival locally without a full list reload', async () => {
    const user = userEvent.setup();
    render(<BatchMonitorPage />);
    await screen.findByText('ABC260701');
    const initialCalls = apiMocks.batchMonitor.mock.calls.length;
    const initialCopyListCalls = apiMocks.batchCopyLists.mock.calls.length;

    await user.click(screen.getByRole('button', { name: '完成美工图' }));
    await waitFor(() => expect(apiMocks.updateBatchArtwork).toHaveBeenCalledWith('ABC260701', true));
    expect(apiMocks.batchMonitor).toHaveBeenCalledTimes(initialCalls);
    expect(screen.getByText('2026-07-30')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '展开ABC260701' }));
    await screen.findByText('SKU-A01');
    await user.click(screen.getByRole('button', { name: '标记到货' }));
    await user.click(screen.getByRole('button', { name: '保存到货' }));
    await waitFor(() => expect(apiMocks.updateSkuArrival).toHaveBeenCalledWith(
      'SKU-A01',
      true,
      expect.any(String),
    ));
    expect(apiMocks.batchMonitor).toHaveBeenCalledTimes(initialCalls);
    expect(apiMocks.batchCopyLists).toHaveBeenCalledTimes(initialCopyListCalls + 1);
  });

  it('creates a batch with a manually entered batch number and workbook', async () => {
    const user = userEvent.setup();
    render(<BatchMonitorPage />);
    await screen.findByText('ABC260701');

    await user.click(screen.getByRole('button', { name: /新建批次/ }));
    await user.type(screen.getByPlaceholderText('例如 FAK260701'), 'new260701');
    const fileInput = document.querySelector('.batch-create-form input[type="file"]') as HTMLInputElement;
    const file = new File(['xlsx'], 'new.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole('button', { name: '创建批次' }));

    await waitFor(() => expect(apiMocks.createBatch).toHaveBeenCalledWith('NEW260701', file));
  });

  it('fills a shipment arrival date from the detail shortcut', async () => {
    const user = userEvent.setup();
    render(<BatchMonitorPage />);
    await screen.findByText('ABC260701');
    await user.click(screen.getByRole('button', { name: '展开ABC260701' }));
    await screen.findByText('SKU-A01');

    await user.click(screen.getByRole('button', { name: /FBA-FIRST.*整票到货/ }));
    expect(screen.getByRole('textbox', { name: '货件单号' })).toHaveValue('FBA-FIRST');
    await user.click(screen.getByRole('button', { name: '保存整票到货' }));

    await waitFor(() => expect(apiMocks.updateShipmentArrival).toHaveBeenCalledWith(
      'FBA-FIRST',
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    ));
  });
});
