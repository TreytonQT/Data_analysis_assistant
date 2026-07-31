import { cleanup, render, screen } from '@testing-library/react';
import dayjs from 'dayjs';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type LastPromotionRecord, type PromotionCandidate, type PromotionOverview, type PromotionRecord } from './api';
import PromotionBoard, { parseManualSkus, promotionDataTabFromSearch, promotionDateRange, promotionRuleLabel, promotionStatusLabel, skuCopyText, writeClipboard } from './PromotionBoard';

afterEach(() => cleanup());

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
  promotion_name: '夏季清仓',
  asin_snapshot: 'ASIN-A',
  developer_snapshot: '开发员乙',
  start_date: '2026-07-01',
  end_date: null,
  status: 'active',
  source_missing: false,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
};

const lastPromotion: LastPromotionRecord = {
  sku: 'SKU-ACTIVE',
  promotion_content: '7/1~7/31 夏季清仓 -10%',
  promotion_id: 'promotion-1',
  promotion_name: '夏季清仓',
  discount_percent: 10,
  start_date: '2026-07-01',
  end_date: '2026-07-31',
  updated_at: '2026-07-01T00:00:00Z',
};

const overview: PromotionOverview = {
  active_sku_count: 1,
  average_7d_total: 2,
  average_30d_total: 1,
  daily_lift_total: 1,
  daily_lift_average: 1,
  by_promotion: [{ promotion_name: '夏季清仓', discount_percents: [10], start_date: '2026-07-01', end_date: '2026-07-31', status: 'active', sku_count: 1, average_7d: 2, average_30d: 1, daily_lift: 1 }],
  developers: ['开发员甲', '开发员乙'],
  updated_at: '2026-07-17T10:00:00Z',
};

describe('PromotionBoard helpers', () => {
  it('formats status, rule and copy text consistently', () => {
    expect(promotionStatusLabel('active')).toBe('正在促销');
    expect(promotionRuleLabel('aged_90d', 5)).toBe('90天以上库存兜底');
    expect(promotionRuleLabel('manual', 12)).toBe('手动添加');
    expect(skuCopyText([' SKU-A ', 'SKU-A', '', 'SKU-B'])).toBe('SKU-A\nSKU-B');
    expect(parseManualSkus(' SKU-A \n\nSKU-A\r\nSKU-B')).toEqual(['SKU-A', 'SKU-B']);
    expect(promotionDateRange('2026-07-01', '2026-07-31')).toBe('2026-07-01 至 2026-07-31');
    expect(promotionDateRange('2026-07-01', null)).toBe('2026-07-01 至 持续促销');
    expect(promotionDataTabFromSearch('?promotion_view=candidates-8')).toBe('candidates-8');
    expect(promotionDataTabFromSearch('?promotion_view=unknown')).toBe('records');
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
    window.history.replaceState({}, '', '/?page=slow-moving&tab=promotion');
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
    vi.spyOn(api, 'lastPromotions').mockResolvedValue({
      columns: [], rows: [lastPromotion], page: 1, page_size: 50, total: 1,
    });
    vi.spyOn(api, 'createPromotions').mockResolvedValue({ created: [] });
    vi.spyOn(api, 'createManualPromotions').mockResolvedValue({
      created: [{ ...activeRecord, sku: 'SKU-MANUAL', discount_percent: 12, rule_key: 'manual' }],
      replaced: 0,
    });
  });

  it('renders active status and opens the promotion dialog from a candidate row', async () => {
    const user = userEvent.setup();
    render(<PromotionBoard />);

    expect(await screen.findByText('SKU-ACTIVE')).toBeInTheDocument();
    expect(screen.getAllByText('正在促销').length).toBeGreaterThan(0);
    expect(api.promotionCandidates).not.toHaveBeenCalled();
    await user.click(screen.getByRole('tab', { name: '促销候选 -10%' }));
    expect(await screen.findByText('SKU-CANDIDATE')).toBeInTheDocument();

    const markButton = screen.getAllByRole('button', { name: /标记促销/ })
      .find(button => button.textContent?.trim() === '标记促销');
    expect(markButton).toBeDefined();
    await user.click(markButton!);
    expect(await screen.findByRole('dialog', { name: '标记正在促销' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('例如：8月会员日促销')).toBeInTheDocument();
  });

  it('opens the manual promotion form with all required inputs', async () => {
    const user = userEvent.setup();
    render(<PromotionBoard />);

    await screen.findByText('SKU-ACTIVE');
    await user.click(screen.getByRole('button', { name: /手动添加促销 SKU/ }));
    expect(await screen.findByRole('dialog', { name: '手动添加促销 SKU' })).toBeInTheDocument();
    expect(screen.getByLabelText('SKU（一行一个）')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('例如：8月会员日促销')).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: '促销力度' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('开始日期')).toHaveValue(dayjs().format('YYYY-MM-DD'));
    expect(screen.getByPlaceholderText('结束日期（可留空）')).toHaveValue('');
  });

  it('restores the last-promotion tab from the URL and fetches only its table', async () => {
    window.history.replaceState({}, '', '/?page=slow-moving&tab=promotion&promotion_view=last-promotions');
    render(<PromotionBoard />);

    expect(await screen.findByText('7/1~7/31 夏季清仓 -10%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /导出 CSV/ })).toBeInTheDocument();
    expect(api.lastPromotions).toHaveBeenCalledTimes(1);
    expect(api.promotionRecords).not.toHaveBeenCalled();
    expect(api.promotionCandidates).not.toHaveBeenCalled();
  });
});
