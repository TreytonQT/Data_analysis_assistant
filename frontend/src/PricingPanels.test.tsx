import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { feedbackMessage } from './feedback';
import { PricingBatches, PricingHistory } from './PricingPanels';

const row = {
  id: 'adjust-1', sku: 'SKU-A', type: 'adjustment' as const, name: '调价批次',
  discount_percent: 10, start_date: '2026-10-01', end_date: null, status: 'active' as const,
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('pricing panel interaction standards', () => {
  it('retries a failed read without navigating away', async () => {
    const user = userEvent.setup();
    const read = vi.spyOn(api, 'pricingBatches').mockRejectedValueOnce(new Error('暂时无法读取')).mockResolvedValue({ rows: [] });
    render(<PricingBatches refreshToken={0} onRegister={vi.fn()} />);
    expect(await screen.findByText('暂时无法读取')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /重.*试/ }));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('暂时无法读取')).not.toBeInTheDocument());
  });

  it('requires a correction reason and preserves the open dialog during a slow save', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'pricingHistory').mockResolvedValue({ rows: [row] });
    let finish!: () => void;
    const request = vi.spyOn(api, 'voidAdjustment').mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    vi.spyOn(feedbackMessage, 'success').mockImplementation(() => undefined as never);
    const onRefresh = vi.fn();
    render(<ConfigProvider theme={{ token: { motion: false } }}><PricingHistory refreshToken={0} onRegister={vi.fn()} onRefresh={onRefresh} /></ConfigProvider>);
    await user.click(await screen.findByRole('button', { name: /作.*废/ }));
    const confirm = screen.getByRole('button', { name: '确认作废' });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText('作废原因'), '重复登记');
    await user.click(confirm);
    expect(request).toHaveBeenCalledWith('adjust-1', '重复登记');
    expect(screen.getByRole('button', { name: /取.*消/ })).toBeDisabled();
    expect(screen.getByLabelText('作废原因')).toHaveValue('重复登记');
    expect(screen.getByLabelText('作废原因')).toBeDisabled();
    await act(async () => finish());
    expect(onRefresh).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
