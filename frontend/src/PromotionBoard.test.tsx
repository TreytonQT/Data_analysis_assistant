import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type PromotionCandidate, type PromotionOverview, type PromotionRecord } from './api';
import PromotionBoard, { promotionRuleLabel, promotionStatusLabel, skuCopyText, writeClipboard } from './PromotionBoard';

const candidate: PromotionCandidate = {
  sku: 'SKU-CANDIDATE',
  asin: 'ASIN-C',
  developer: '开发员甲',
  available_inventory: 25,
  sales_90d: 8,
  aged_inventory_90d: 3,
  average_7d: 2,
  average_30d: 1,
  daily_lift: 1,
  discount_percent: 10,
  rule_key: 'sales_le_10',
};

const activeRecord: PromotionRecord = {
  ...candidate,
  id: 'promotion-1',
  sku: 'SKU-ACTIVE',
  asin_snapshot: 'ASIN-A',
  developer_snapshot: '开发员乙',
  start_date: '2026-07-01',
  end_date: null,
  status: 'active',
  source_missing: false,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
};

const overview: PromotionOverview = {
  active_sku_count: 1,
  average_7d_total: 2,
  average_30d_total: 1,
  daily_lift_total: 1,
  daily_lift_average: 1,
  by_discount: [{ discount_percent: 10, sku_count: 1, average_7d: 2, average_30d: 1, daily_lift: 1 }],
  developers: ['开发员甲', '开发员乙'],
  updated_at: '2026-07-17T10:00:00Z',
};

describe('PromotionBoard helpers', () => {
  it('formats status, rule and copy text consistently', () => {
    expect(promotionStatusLabel('active')).toBe('正在促销');
    expect(promotionRuleLabel('aged_90d', 5)).toBe('90天以上库存兜底');
    expect(skuCopyText([' SKU-A ', 'SKU-A', '', 'SKU-B'])).toBe('SKU-A\nSKU-B');
  });

  it('reports clipboard permission failures after the fallback also fails', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    });
    await expect(writeClipboard('SKU-A')).rejects.toThrow('剪贴板写入失败');
  });
});

describe('PromotionBoard component', () => {
  beforeEach(() => {
    vi.spyOn(api, 'promotionOverview').mockResolvedValue(overview);
    vi.spyOn(api, 'promotionCandidates').mockImplementation(async discount => ({
      columns: [],
      rows: discount === 10 ? [candidate] : [],
      page: 1,
      page_size: 50,
      total: discount === 10 ? 1 : 0,
      developers: ['开发员甲'],
    }));
    vi.spyOn(api, 'promotionRecords').mockResolvedValue({
      columns: [], rows: [activeRecord], page: 1, page_size: 50, total: 1, developers: ['开发员乙'],
    });
    vi.spyOn(api, 'createPromotions').mockResolvedValue({ created: [] });
  });

  it('renders active status and opens the promotion dialog from a candidate row', async () => {
    const user = userEvent.setup();
    render(<PromotionBoard />);

    expect(await screen.findByText('SKU-ACTIVE')).toBeInTheDocument();
    expect(screen.getAllByText('正在促销').length).toBeGreaterThan(0);
    expect(await screen.findByText('SKU-CANDIDATE')).toBeInTheDocument();

    const markButton = screen.getAllByRole('button', { name: /标记促销/ })
      .find(button => button.textContent?.trim() === '标记促销');
    expect(markButton).toBeDefined();
    await user.click(markButton!);
    expect(await screen.findByRole('dialog', { name: '标记正在促销' })).toBeInTheDocument();
  });
});
