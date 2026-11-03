import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { feedbackMessage } from './feedback';
import UploadCenter, { uploadFrequencyTabFromSearch } from './UploadCenter';

const mocks = vi.hoisted(() => ({ reports: vi.fn(), uploadReports: vi.fn() }));

vi.mock('./api', () => ({
  api: { reports: mocks.reports, uploadReports: mocks.uploadReports },
  apiErrorMessage: (_payload: unknown, fallback = '请求失败') => fallback,
}));

describe('UploadCenter', () => {
  beforeEach(() => {
    mocks.reports.mockResolvedValue({ reports: [{ 月份: '2026-08', 原始文件名: 'report.csv', 上传时间: '2026-08-06 10:00:00', 文件大小: 1024 }], sources: {} });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.history.replaceState({}, '', '/');
    vi.clearAllMocks();
  });

  it('defaults invalid or missing URL tabs to daily uploads', () => {
    expect(uploadFrequencyTabFromSearch('?page=uploads')).toBe('daily');
    expect(uploadFrequencyTabFromSearch('?page=uploads&tab=unknown')).toBe('daily');
    expect(uploadFrequencyTabFromSearch('?page=uploads&tab=weekly')).toBe('weekly');
    expect(uploadFrequencyTabFromSearch('?page=uploads&tab=monthly')).toBe('monthly');
  });

  it('groups upload cards and records by frequency tab', async () => {
    window.history.replaceState({}, '', '/?page=uploads');
    render(<UploadCenter />);

    expect(await screen.findByTestId('source-operational_sales')).toBeInTheDocument();
    expect(screen.getByTestId('source-gross_profit')).toBeInTheDocument();
    expect(screen.getByTestId('source-sales_volume_detail')).toBeInTheDocument();
    expect(screen.getByTestId('source-sales_amount_detail')).toBeInTheDocument();
    expect(screen.queryByTestId('source-rating')).not.toBeInTheDocument();
    expect(screen.queryByTestId('performance-reports')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sales-history-rolling')).not.toBeInTheDocument();

    window.history.pushState({}, '', '/?page=uploads&tab=weekly');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByTestId('performance-reports')).toBeInTheDocument());
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('weekly');
    expect(screen.getByTestId('source-rating')).toBeInTheDocument();
    expect(screen.getByTestId('performance-reports')).toBeInTheDocument();
    expect(screen.queryByTestId('source-operational_sales')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sales-history-rolling')).not.toBeInTheDocument();

    window.history.pushState({}, '', '/?page=uploads&tab=monthly');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByTestId('sales-history-rolling')).toBeInTheDocument());
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('monthly');
    expect(screen.getByTestId('source-sku_image_map')).toBeInTheDocument();
    expect(screen.getByText('新版字段：MSKU、ASIN、图片链接；按 MSKU + ASIN 关联图片，空链接跳过并显示无图片')).toBeInTheDocument();
    expect(screen.getByTestId('sales-history-rolling')).toBeInTheDocument();
    expect(screen.queryByTestId('performance-reports')).not.toBeInTheDocument();
  });

  it('restores the selected tab from browser navigation', async () => {
    window.history.replaceState({}, '', '/?page=uploads&tab=weekly');
    render(<UploadCenter />);
    expect(await screen.findByTestId('performance-reports')).toBeInTheDocument();

    window.history.pushState({}, '', '/?page=uploads&tab=monthly');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByTestId('sales-history-rolling')).toBeInTheDocument());
    expect(screen.queryByTestId('performance-reports')).not.toBeInTheDocument();
  });

  it('keeps upload warnings and refreshes records after the shared upload succeeds', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/?page=uploads');
    mocks.reports.mockResolvedValue({ reports: [], sources: {} });
    mocks.uploadReports.mockResolvedValue({ warnings: ['保留已有价格'] });
    vi.spyOn(feedbackMessage, 'loading').mockImplementation(() => undefined as never);
    const warning = vi.spyOn(feedbackMessage, 'warning').mockImplementation(() => undefined as never);
    render(<UploadCenter />);
    const card = await screen.findByTestId('source-operational_sales');
    await waitFor(() => expect(card.closest('.ant-spin-container')).not.toHaveClass('ant-spin-blur'));
    const input = card.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['source'], '运营.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    await user.upload(input, file);
    await waitFor(() => expect(mocks.uploadReports).toHaveBeenCalledWith('/api/reports/source/operational_sales', [file], false));
    expect(warning).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining('保留已有价格') }));
    expect(mocks.reports.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
