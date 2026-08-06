import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ReplenishmentPage, { ReplenishmentDecisionBoard, maxWeightClass } from './ReplenishmentPage';
import type { DashboardPayload, DashboardSection, ReplenishmentGroupRow } from './api';

const apiMocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  dashboardSection: vi.fn(),
  replenishmentGroupDetails: vi.fn(),
  updateReplenishmentSwitch: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    api: {
      ...actual.api,
      dashboard: apiMocks.dashboard,
      dashboardSection: apiMocks.dashboardSection,
      replenishmentGroupDetails: apiMocks.replenishmentGroupDetails,
      updateReplenishmentSwitch: apiMocks.updateReplenishmentSwitch,
    },
  };
});

const row: ReplenishmentGroupRow = {
  group_id: 'B001',
  identity: {
    asin: 'B001',
    original_sku: 'SKU-1',
    follower_skus: ['SKU-2', 'SKU-3', 'SKU-4'],
    sku_count: 4,
    stores: ['ZXU'],
    store_statuses: ['ZXU·正常'],
    developers: ['张三'],
    tags: [{ label: '爆款', color: '#16A34A' }],
    rating: { review_count: 120, score: 4.5 },
  },
  countries: {
    DE: { units: 20, margin: 0.25, reasons: [] },
    FR: { units: 10, margin: 0.15, reasons: ['SKU-2: 广告炸'] },
    ES: { units: 2, margin: 0.05, reasons: [] },
    IT: { units: 1, margin: -0.1, reasons: ['SKU-3: 退货多'] },
  },
  inventory: {
    amazon_available: 30,
    group_total: 50,
    asin_reference_total: 50,
    aged_over_90: 5,
    aged_180_to_365: 2,
    aged_over_365: 1,
    is_split_reference: false,
  },
  trend: { t_value: 1.5, calibrated_daily_sales: 4, max_weight_g: 120, coverage_days: 90 },
  promotion: { start_date: '2026-08-01', end_date: '2026-08-10', discount_percent: 10 },
  history: {
    available: true,
    site_sales: { DE: 120, FR: 80, ES: 60, IT: 40 },
    peak_months: [
      { month: '2026-06', total_sales: 90, included_days: 15, adjusted_daily_average: 6 },
      { month: '2026-07', total_sales: 68, included_days: 21, adjusted_daily_average: 3.24 },
    ],
  },
  recommendation: {
    target_inventory: 360,
    measured_quantity: 310,
    official_quantity: 310,
    enabled: true,
    close_reason: '',
    status: '正常',
    errors: [],
  },
};

describe('ReplenishmentDecisionBoard', () => {
  const section = (): DashboardSection => ({
    key: 'detail',
    title: 'ASIN补货汇总',
    columns: [],
    rows: [{ ASIN: 'B001', 补货组ID: 'B001' }],
    page: 1,
    page_size: 50,
    total: 1,
    paginated: false,
    group_rows: [row],
  });
  const payload = (): DashboardPayload => ({
    title: '补货管理',
    has_data: true,
    filters: { developers: ['张三', '李四'] },
    selected: { developers: [] },
    metrics: [
      { name: '需补货ASIN数', value: 1 },
      { name: '建议补货总量', value: 310 },
      { name: '数据异常ASIN数', value: 0 },
    ],
    sections: [section()],
    group_rows: [row],
  });

  beforeEach(() => {
    apiMocks.dashboard.mockReset().mockResolvedValue(payload());
    apiMocks.dashboardSection.mockReset().mockResolvedValue(section());
    apiMocks.replenishmentGroupDetails.mockReset();
    apiMocks.updateReplenishmentSwitch.mockReset().mockResolvedValue({
      ASIN: 'B001',
      is_replenishment: false,
      close_reason: '停售',
      updated_at: '2026-07-30T10:00:00+08:00',
    });
  });

  afterEach(() => cleanup());

  it('renders every decision group without using a native table', () => {
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[row]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    expect(container.querySelector('table')).not.toBeInTheDocument();
    expect(screen.getByRole('grid', { name: 'ASIN补货运营决策矩阵' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '补货决策' })).toBeInTheDocument();
    expect(screen.getByText('建议补货数量')).toBeInTheDocument();
    expect(screen.getAllByText('310')).toHaveLength(2);
    expect(container.querySelector('.margin-healthy')).toHaveTextContent('25.0%');
    expect(container.querySelector('.margin-warning')).toHaveTextContent('15.0%');
    expect(container.querySelector('.margin-negative')).toHaveTextContent('-10.0%');
    expect(container.querySelector('.rating-healthy')).toHaveTextContent('120（4.5）');
    expect(container.querySelector('.weight-warning')).toHaveTextContent('120g');
    expect(screen.queryByRole('columnheader', { name: '促销与运营' })).not.toBeInTheDocument();
  });

  it('highlights maximum weight from 100g inclusively', () => {
    expect(maxWeightClass(99.99)).toBe('');
    expect(maxWeightClass(100)).toBe('weight-warning');
    expect(maxWeightClass(100.01)).toBe('weight-warning');
    expect(maxWeightClass(null)).toBe('');
  });

  it('supports expanding a group with a keyboard-accessible button', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <ReplenishmentDecisionBoard
        rows={[row]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={onToggle}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: '展开B001明细' }));
    expect(onToggle).toHaveBeenCalledWith('B001');
  });

  it('offers a row-level no-replenishment action and an explicit missing-rating state', async () => {
    const user = userEvent.setup();
    const onDisable = vi.fn();
    const missingRatingRow = { ...row, identity: { ...row.identity, rating: null } };
    render(
      <ReplenishmentDecisionBoard
        rows={[missingRatingRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={onDisable}
      />,
    );

    expect(screen.getByText('暂无Rating')).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'B001补货开关' }));
    await user.click(await screen.findByText('不补货'));
    expect(onDisable).toHaveBeenCalledWith(missingRatingRow);
  });

  it('defaults to min quantity 30 and can select all matched developers', async () => {
    const user = userEvent.setup();
    render(<ReplenishmentPage />);

    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenCalledWith('replenishment', { min_qty: '30' }));
    const developerSelect = screen.getByRole('combobox', { name: '开发员筛选' });
    await user.click(developerSelect);
    await user.type(developerSelect, '张');
    await user.click(await screen.findByText('全选当前搜索结果（1）'));

    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenCalledWith('replenishment', {
      developers: '张三',
      min_qty: '30',
    }));
  });

  it('changes the server-side quantity threshold and requires a close reason', async () => {
    const user = userEvent.setup();
    render(<ReplenishmentPage />);
    await screen.findByRole('grid', { name: 'ASIN补货运营决策矩阵' });

    await user.click(screen.getByRole('combobox', { name: '建议补货数量门槛' }));
    await user.click(await screen.findByText('≥50'));
    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenCalledWith('replenishment', { min_qty: '50' }));
    const dashboardCallsBeforeSwitch = apiMocks.dashboard.mock.calls.length;
    const sectionCallsBeforeSwitch = apiMocks.dashboardSection.mock.calls.length;

    await user.click(screen.getByRole('combobox', { name: 'B001补货开关' }));
    await user.click(await screen.findByText('不补货'));
    const confirm = screen.getByRole('button', { name: '确认不补货' });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByPlaceholderText('请输入不补货原因（必填）'), '停售');
    await user.click(confirm);
    await waitFor(() => expect(apiMocks.updateReplenishmentSwitch).toHaveBeenCalledWith('B001', false, '停售'));
    await waitFor(() => expect(screen.queryByRole('button', { name: '展开B001明细' })).not.toBeInTheDocument());
    expect(apiMocks.dashboard).toHaveBeenCalledTimes(dashboardCallsBeforeSwitch);
    expect(apiMocks.dashboardSection).toHaveBeenCalledTimes(sectionCallsBeforeSwitch);
  });
});
