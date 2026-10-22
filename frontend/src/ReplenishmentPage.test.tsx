import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ReplenishmentPage, { ReplenishmentDecisionBoard, SkuDetailPanel, maxWeightClass } from './ReplenishmentPage';
import type { DashboardPayload, DashboardSection, ReplenishmentGroupRow } from './api';

const apiMocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  dashboardSection: vi.fn(),
  replenishmentPricing: vi.fn(),
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
      replenishmentPricing: apiMocks.replenishmentPricing,
      replenishmentGroupDetails: apiMocks.replenishmentGroupDetails,
      updateReplenishmentSwitch: apiMocks.updateReplenishmentSwitch,
    },
  };
});

const row: ReplenishmentGroupRow = {
  group_id: 'B001',
  identity: {
    asin: 'B001',
    image: null,
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
    site_sales: { DE: 40, FR: 120, ES: 20, IT: 80 },
    site_sales_source: 'sales_volume_detail',
    site_sales_available: true,
    site_sales_matched: true,
    site_sales_days: 30,
    site_sales_period_start: '2026-08-16',
    site_sales_period_end: '2026-09-14',
    recent_sales: { yesterday: 8, day_before_yesterday: 6, two_days_before: 5 },
    period_sales: { days_7: 50, days_14: 96, days_30: 210, days_90: 720 },
    peak_months: [
      { month: '2026-07', total_sales: 68, included_days: 21, adjusted_daily_average: 3.24 },
      { month: '2026-06', total_sales: 90, included_days: 15, adjusted_daily_average: 6 },
    ],
    months: [
      { month: '2025-10', total_sales: 0, included_days: 31, adjusted_daily_average: 0 },
      { month: '2025-11', total_sales: 12, included_days: 30, adjusted_daily_average: 0.4 },
      { month: '2025-12', total_sales: 20, included_days: 31, adjusted_daily_average: 0.65 },
      { month: '2026-01', total_sales: 0, included_days: 31, adjusted_daily_average: 0 },
      { month: '2026-02', total_sales: 35, included_days: 28, adjusted_daily_average: 1.25 },
      { month: '2026-03', total_sales: 42, included_days: 31, adjusted_daily_average: 1.35 },
      { month: '2026-04', total_sales: 56, included_days: 30, adjusted_daily_average: 1.87 },
      { month: '2026-05', total_sales: 61, included_days: 31, adjusted_daily_average: 1.97 },
      { month: '2026-06', total_sales: 90, included_days: 15, adjusted_daily_average: 6 },
      { month: '2026-07', total_sales: 68, included_days: 21, adjusted_daily_average: 3.24 },
      { month: '2026-08', total_sales: 75, included_days: 31, adjusted_daily_average: 2.42 },
      { month: '2026-09', total_sales: 80, included_days: 17, adjusted_daily_average: 4.71 },
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

const priceRow: ReplenishmentGroupRow = {
  ...row,
  pricing: {
    status: '一致',
    recent_event: null,
    countries: {
      DE: {
        current_price: 20,
        launch_price: 10,
        launch_change: 1,
        status: '有价格',
        representative_sku: 'SKU-1',
        history: [
          { date: '2026-09-16', current_price: 10, listing_price: 12, promotion_price: 10, currency: 'EUR', is_promotion: true, is_available: true },
          { date: '2026-09-17', current_price: 20, listing_price: 20, promotion_price: null, currency: 'EUR', is_promotion: false, is_available: true, previous_price: 10, amount_change: 10, percent_change: 1 },
        ],
      },
      FR: { current_price: null, launch_price: null, launch_change: null, status: '无当前价', history: [] },
      ES: { current_price: null, launch_price: null, launch_change: null, status: '无当前价', history: [] },
      IT: { current_price: null, launch_price: null, launch_change: null, status: '无当前价', history: [] },
    },
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
    apiMocks.replenishmentPricing.mockReset().mockResolvedValue({ revision: 'test', rows: { B001: priceRow.pricing } });
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
    expect(screen.getByText('近3日')).toBeInTheDocument();
    expect(screen.getByText('4站点销量（30天）')).toBeInTheDocument();
    expect(screen.getByText('月份销量')).toBeInTheDocument();
    expect(screen.getByText('昨天')).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.replenishment-history-site-group .replenishment-history-group-item em')).map(item => item.textContent)).toEqual(['FR', 'IT', 'DE', 'ES']);
    expect(container.querySelector('.replenishment-monthly-chart.compact')).toBeInTheDocument();
    expect(container.querySelectorAll('.replenishment-monthly-chart-total-path')).toHaveLength(1);
    expect(container.querySelectorAll('.replenishment-monthly-chart-average-path')).toHaveLength(1);
    expect(container.querySelectorAll('.replenishment-monthly-chart-total-point')).toHaveLength(12);
    expect(container.querySelector('.replenishment-monthly-chart-total-path')?.getAttribute('d')).toContain(' C ');
    expect(container.querySelector('.replenishment-monthly-chart-average-path')?.getAttribute('d')).toContain(' C ');
    expect(container.querySelector('.replenishment-monthly-chart-total-area')).toBeInTheDocument();
    expect(container.querySelector('linearGradient')).toBeInTheDocument();
    expect(container.querySelector('.replenishment-monthly-chart-hit-area')).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.replenishment-monthly-chart.compact .replenishment-monthly-chart-month-label')).map(item => item.textContent)).toEqual(['2025-10', '2026-09']);
    expect(container.querySelector('.replenishment-history-groups-main')).toBeInTheDocument();
    expect(container.querySelector('.replenishment-board-row')).toHaveClass('has-monthly-history');
    expect(screen.getAllByText('310')).toHaveLength(2);
    expect(container.querySelector('.margin-healthy')).toHaveTextContent('25.0%');
    expect(container.querySelector('.margin-warning')).toHaveTextContent('15.0%');
    expect(container.querySelector('.margin-negative')).toHaveTextContent('-10.0%');
    expect(container.querySelector('.rating-healthy')).toHaveTextContent('120（4.5）');
    expect(container.querySelector('.weight-warning')).toHaveTextContent('120g');
    expect(screen.getByLabelText('B001暂无图片')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: '促销与运营' })).not.toBeInTheDocument();
  });

  it('renders a country price step chart with a snapped portal tooltip', () => {
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[priceRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );
    const chart = container.querySelector('.replenishment-price-trend-svg') as SVGSVGElement;
    const hitArea = container.querySelector('.replenishment-price-trend-hit-area') as SVGRectElement;
    expect(container.querySelectorAll('.replenishment-price-trend-svg')).toHaveLength(1);
    expect(container.querySelector('.replenishment-price-trend-segment')).toHaveAttribute('d', expect.stringContaining('H'));
    vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({
      left: 100, top: 100, width: 190, height: 58, right: 290, bottom: 158, x: 100, y: 100,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerMove(hitArea, { clientX: 285, clientY: 125, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('当前实际总价 20');
    expect(screen.getByRole('tooltip')).toHaveTextContent('原价 / 优惠 20 / —');
    expect(container.querySelector('.replenishment-price-trend-crosshair')).toBeInTheDocument();
    fireEvent.pointerLeave(hitArea, { pointerType: 'mouse' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
  it('keeps rows without monthly history compact and shows the missing chart state', () => {
    const compactRow = {
      ...row,
      pricing: undefined,
      history: { ...row.history, months: [], peak_months: [] },
    };
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[compactRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    expect(container.querySelector('.replenishment-board-row')).not.toHaveClass('has-monthly-history');
    expect(container.querySelector('.replenishment-history-month-group .replenishment-history-group-empty')).toHaveTextContent('—');
    expect(container.querySelector('.replenishment-monthly-chart.compact')).not.toBeInTheDocument();
  });

  it('snaps the mini chart to the closest month and shows a portal tooltip', () => {
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
    const svg = container.querySelector('.replenishment-monthly-chart.compact .replenishment-monthly-chart-svg') as SVGSVGElement;
    const hitArea = container.querySelector('.replenishment-monthly-chart.compact .replenishment-monthly-chart-hit-area') as SVGRectElement;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      left: 100, top: 100, width: 360, height: 86, right: 460, bottom: 186, x: 100, y: 100,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerMove(hitArea, { clientX: 108, clientY: 140, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('2025-10');
    expect(screen.getByRole('tooltip')).toHaveTextContent('月总销量 0 件');
    expect(container.querySelector('.replenishment-monthly-chart-crosshair')).toHaveAttribute('data-index', '0');
    expect(container.querySelectorAll('.replenishment-monthly-chart-total-point.is-active')).toHaveLength(1);
    expect(container.querySelectorAll('.replenishment-monthly-chart-average-point.is-active')).toHaveLength(1);
    act(() => { window.dispatchEvent(new Event('resize')); });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    fireEvent.pointerMove(hitArea, { clientX: 452, clientY: 140, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('2026-09');
    expect(container.querySelector('.replenishment-monthly-chart-crosshair')).toHaveAttribute('data-index', '11');
    act(() => { window.dispatchEvent(new Event('scroll')); });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.pointerMove(hitArea, { clientX: 108, clientY: 140, pointerType: 'mouse' });
    fireEvent.pointerLeave(hitArea, { pointerType: 'mouse' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('uses the same snapped tooltip interaction in the expanded chart', () => {
    const { container } = render(
      <SkuDetailPanel
        loading={false}
        onRetry={vi.fn()}
        details={{
          group: {},
          sku_columns: [],
          sales_history: { ...row.history, title: '近12个月销量画像', months: row.history.months },
          sku_rows: [],
        }}
      />,
    );
    const svg = container.querySelector('.replenishment-monthly-chart.full .replenishment-monthly-chart-svg') as SVGSVGElement;
    const hitArea = container.querySelector('.replenishment-monthly-chart.full .replenishment-monthly-chart-hit-area') as SVGRectElement;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 80, width: 960, height: 250, right: 960, bottom: 330, x: 0, y: 80,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerMove(hitArea, { clientX: 480, clientY: 170, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('2026-04');
    expect(screen.getByRole('tooltip')).toHaveTextContent('月总销量 56 件');
    expect(screen.getByRole('tooltip')).toHaveTextContent('校准日均 1.87/天');
    expect(container.querySelector('.replenishment-monthly-chart.full .replenishment-monthly-chart-crosshair')).toHaveAttribute('data-index', '6');
  });

  it('shows a placeholder instead of NaN for an invalid adjusted daily average', () => {
    const invalidAverageRow = {
      ...row,
      history: {
        ...row.history,
        months: [
          { month: '2026-07', total_sales: 0, included_days: 31, adjusted_daily_average: 0 },
          { month: '2026-08', total_sales: 12, included_days: 0, adjusted_daily_average: Number.NaN },
        ],
        peak_months: [
          { month: '2026-08', total_sales: 12, included_days: 0, adjusted_daily_average: Number.NaN },
          { month: '2026-07', total_sales: 0, included_days: 31, adjusted_daily_average: 0 },
        ],
      },
    };
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[invalidAverageRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    expect(container.querySelector('.replenishment-monthly-chart.compact')).toBeInTheDocument();
    expect(container.querySelectorAll('.replenishment-monthly-chart-total-point')).toHaveLength(2);
    expect(container.textContent).not.toContain('NaN');
  });

  it('keeps the mini chart visible while an older response only has peak months', () => {
    const legacyHistoryRow = { ...row, history: { ...row.history, months: undefined } };
    const { container } = render(
      <ReplenishmentDecisionBoard rows={[legacyHistoryRow]} expanded={new Set()} details={{}}
        detailLoading={new Set()} detailErrors={{}} onToggle={vi.fn()} onRetry={vi.fn()} onDisable={vi.fn()} />,
    );
    expect(container.querySelector('.replenishment-monthly-chart.compact')).toBeInTheDocument();
    expect(container.querySelectorAll('.replenishment-monthly-chart-total-point')).toHaveLength(2);
  });

  it('shows sales detail independently of monthly history and preserves missing versus zero', () => {
    const { container, rerender } = render(
      <ReplenishmentDecisionBoard rows={[{ ...row, history: { ...row.history, available: false, peak_months: [],
        site_sales_days: 2, site_sales: { DE: 0, FR: 12, ES: 0, IT: 0 },
        site_sales_period_start: '2026-08-31', site_sales_period_end: '2026-09-01' } }]}
        expanded={new Set()} details={{}} detailLoading={new Set()} detailErrors={{}}
        onToggle={vi.fn()} onRetry={vi.fn()} onDisable={vi.fn()} />,
    );
    expect(screen.getByText('4站点销量（2天）')).toHaveAttribute('title', '销量明细：2026-08-31 至 2026-09-01');
    expect(Array.from(container.querySelectorAll('.replenishment-history-site-group strong')).map(item => item.textContent)).toEqual(['12', '0', '0', '0']);
    rerender(<ReplenishmentDecisionBoard rows={[{ ...row, history: { ...row.history,
      site_sales: { DE: null, FR: null, ES: null, IT: null } } }]}
      expanded={new Set()} details={{}} detailLoading={new Set()} detailErrors={{}}
      onToggle={vi.fn()} onRetry={vi.fn()} onDisable={vi.fn()} />);
    expect(Array.from(container.querySelectorAll('.replenishment-history-site-group strong')).map(item => item.textContent)).toEqual(['—', '—', '—', '—']);
  });

  it('renders an ASIN image with a previewable source', () => {
    const imageRow = {
      ...row,
      identity: {
        ...row.identity,
        image: {
          url: 'https://cdn.example.com/SKU-1.jpg',
          inventory_sku: 'MITSKU-1',
          virtual_sku: 'SKU-1',
          source_role: 'original' as const,
        },
      },
    };
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[imageRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    const image = container.querySelector('.replenishment-asin-image');
    expect(image).toHaveAttribute('src', 'https://cdn.example.com/SKU-1.jpg');
    expect(image).toHaveAttribute('alt', 'B001库存图片');
  });

  it('retries a failed ASIN image with cache-busting URLs', () => {
    const imageRow = {
      ...row,
      identity: {
        ...row.identity,
        image: {
          url: 'https://m.media-amazon.com/images/I/71gJjvXH+kL.jpg',
          inventory_sku: 'MDEYIP251101CQT050',
          virtual_sku: 'YIP251101CQT050',
          source_role: 'original' as const,
        },
      },
    };
    render(
      <ReplenishmentDecisionBoard
        rows={[imageRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    let image = screen.getByAltText('B001库存图片');
    expect(image).toHaveAttribute('src', 'https://m.media-amazon.com/images/I/71gJjvXH+kL.jpg');
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer');

    fireEvent.error(image);
    image = screen.getByAltText('B001库存图片');
    expect(image).toHaveAttribute('src', 'https://m.media-amazon.com/images/I/71gJjvXH+kL.jpg?_image_retry=1');

    fireEvent.error(image);
    image = screen.getByAltText('B001库存图片');
    expect(image).toHaveAttribute('src', 'https://m.media-amazon.com/images/I/71gJjvXH+kL.jpg?_image_retry=2');
  });

  it('highlights maximum weight from 100g inclusively', () => {
    expect(maxWeightClass(99.99)).toBe('');
    expect(maxWeightClass(100)).toBe('weight-warning');
    expect(maxWeightClass(100.01)).toBe('weight-warning');
    expect(maxWeightClass(null)).toBe('');
  });

  it('shows independent four-site margins for every expanded SKU', () => {
    const { container } = render(
      <SkuDetailPanel
        loading={false}
        onRetry={vi.fn()}
        details={{
          group: {},
          sku_columns: [],
          sales_history: null,
          sku_rows: [
            { MSKU: 'SKU1', ASIN: 'B001', SKU角色: '原SKU', 德国毛利率: 0.25, 法国毛利率: 0.15, 西班牙毛利率: 0.05, 意大利毛利率: -0.1 },
            { MSKU: 'SKU2', ASIN: 'B001', SKU角色: '跟卖SKU', 德国毛利率: 0.2, 法国毛利率: null, 西班牙毛利率: 0, 意大利毛利率: 0.3 },
          ],
        }}
      />,
    );

    expect(screen.getAllByText('分站点毛利率')).toHaveLength(2);
    expect(container.querySelectorAll('.replenishment-sku-margin-cell.margin-healthy')).toHaveLength(3);
    expect(container.querySelectorAll('.replenishment-sku-margin-cell.margin-warning')).toHaveLength(1);
    expect(container.querySelectorAll('.replenishment-sku-margin-cell.margin-low')).toHaveLength(2);
    expect(container.querySelectorAll('.replenishment-sku-margin-cell.margin-negative')).toHaveLength(1);
    expect(container.querySelectorAll('.replenishment-sku-margin-cell.margin-missing')).toHaveLength(1);
    expect(screen.getByText('25.0%')).toBeInTheDocument();
    expect(container.querySelector('.replenishment-sku-margin-cell.margin-missing strong')).toHaveTextContent('—');
  });

  it('shows the latest actual price change in each country cell', () => {
    const pricedRow = {
      ...row,
      pricing: {
        status: '一致',
        recent_event: null,
        countries: {
          DE: {
            current_price: 5.99,
            launch_price: 5.49,
            launch_change: 0.091,
            status: '上涨',
            latest_change: {
              status: '变价',
              type: '实际总价涨跌',
              date: '2026-09-17',
              previous_date: '2026-09-16',
              gap_days: 1,
              observed_as: '连续观察',
              old_price: 5.49,
              new_price: 5.99,
              amount_change: 0.5,
              percent_change: 0.091,
              sku_count: 1,
              items: [],
            },
          },
          FR: {
            current_price: 8.49,
            launch_price: 6.99,
            launch_change: 0.215,
            status: '上涨',
            latest_change: {
              status: '多SKU变价',
              type: '多SKU变价',
              date: '2026-09-17',
              previous_date: '2026-09-16',
              gap_days: 1,
              observed_as: '连续观察',
              old_price: null,
              new_price: null,
              amount_change: null,
              percent_change: null,
              sku_count: 2,
              representative_sku: 'SKU-HIGH-VOLUME',
              representative_sales: 100,
              representative_old_price: 6.99,
              representative_new_price: 8.49,
              representative_amount_change: 1.5,
              representative_percent_change: 0.2146,
              items: [],
            },
          },
          ES: { current_price: 8.49, launch_price: 6.99, launch_change: 0.215, status: '上涨' },
          IT: { current_price: null, launch_price: 7.49, launch_change: null, status: '无当前价' },
        },
      },
    };
    const { container } = render(
      <ReplenishmentDecisionBoard
        rows={[pricedRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    expect(container.querySelector('.replenishment-board-row')).toHaveClass('has-country-price');
    expect(container.querySelector('.replenishment-price-summary')).toBeNull();
    expect(container.querySelector('.replenishment-country-price.price-increase')).toHaveTextContent('现价 5.99 (+0.5)');
    expect(container.querySelector('.replenishment-country-price.price-increase')).toHaveTextContent('9/16 → 9/17');
    expect(container.querySelectorAll('.replenishment-country-price.price-increase')[1]).toHaveTextContent('现价 8.49 (+1.5)');
    expect(container.querySelectorAll('.replenishment-country-price.price-increase')[1]).toHaveTextContent('代表SKU');
  });

  it('places the sales profile before SKU cards and renders listing price tiles', () => {
    const { container } = render(
      <SkuDetailPanel
        loading={false}
        onRetry={vi.fn()}
        details={{
          group: {},
          sku_columns: [],
          sales_history: { ...row.history, title: '近12个月销量画像', months: row.history.months },
          sku_rows: [{
            MSKU: 'SKU1',
            ASIN: 'B001',
            SKU角色: '原SKU',
            DE_开售价: 5.49,
            DE_当前实际总价: 5.99,
            DE_较开售价变化: 0.091,
            FR_开售价: 6.99,
            FR_当前实际总价: 8.49,
            FR_较开售价变化: 0.215,
            ES_开售价: 6.99,
            ES_当前实际总价: 8.49,
            ES_较开售价变化: 0.215,
            IT_开售价: 7.49,
            IT_当前实际总价: null,
            IT_较开售价变化: null,
            德国毛利率: 0.25,
            法国毛利率: 0.15,
            西班牙毛利率: 0.05,
            意大利毛利率: -0.1,
          }],
        }}
      />,
    );

    const panel = container.querySelector('.replenishment-detail-panel');
    expect(panel).not.toBeNull();
    const children = Array.from(panel!.children);
    expect(children[1]).toHaveClass('replenishment-history-detail');
    expect(children[2]).toHaveClass('replenishment-sku-list');
    expect(screen.getByText('近12个月销量画像')).toBeInTheDocument();
    expect(container.querySelector('.replenishment-monthly-chart.full')).toBeInTheDocument();
    expect(container.querySelectorAll('.replenishment-monthly-chart.full .replenishment-monthly-chart-month-label')).toHaveLength(12);
    expect(container.querySelectorAll('.replenishment-monthly-chart.full .replenishment-monthly-chart-month-grid')).toHaveLength(12);
    expect(Array.from(container.querySelectorAll('.replenishment-history-detail .replenishment-history-site-group .replenishment-history-group-item em')).map(item => item.textContent)).toEqual(['DE', 'FR', 'ES', 'IT']);
    expect(container.querySelectorAll('.replenishment-sku-sections > section')).toHaveLength(4);
    expect(container.querySelectorAll('.replenishment-price-tile')).toHaveLength(4);
    expect(container.querySelector('.price-missing .replenishment-price-delta b')).toHaveTextContent('—');
    expect(screen.getByText('5.49')).toBeInTheDocument();
    expect(screen.getByText('9.1%')).toBeInTheDocument();
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

  it('uses the gray rating state when the review count is zero', () => {
    const zeroRatingRow = { ...row, identity: { ...row.identity, rating: { review_count: 0, score: 0 } } };
    render(
      <ReplenishmentDecisionBoard
        rows={[zeroRatingRow]}
        expanded={new Set()}
        details={{}}
        detailLoading={new Set()}
        detailErrors={{}}
        onToggle={vi.fn()}
        onRetry={vi.fn()}
        onDisable={vi.fn()}
      />,
    );

    expect(screen.getByText('0（0）')).toHaveClass('rating-missing');
    expect(screen.getByText('0（0）')).not.toHaveClass('rating-danger');
  });

  it('defaults to min quantity 30 and can select all matched developers', async () => {
    const user = userEvent.setup();
    render(<ReplenishmentPage />);

    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenCalledWith('replenishment', expect.objectContaining({ include_pricing: 'false', min_qty: '30', page: '1' }), expect.any(AbortSignal)));
    const initialCalls = apiMocks.dashboard.mock.calls.length;
    await user.click(screen.getByRole('button', { name: '开发员筛选: 全部开发员' }));
    await user.type(screen.getByRole('textbox', { name: '搜索开发员筛选' }), '张');
    await user.click(screen.getByRole('checkbox', { name: '全选当前搜索结果' }));
    expect(apiMocks.dashboard).toHaveBeenCalledTimes(initialCalls);
    await user.click(screen.getByRole('button', { name: '确定' }));

    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenLastCalledWith('replenishment', expect.objectContaining({
      developers: '张三',
      include_pricing: 'false',
      min_qty: '30',
      page: '1',
    }), expect.any(AbortSignal)));
  });

  it('changes the server-side quantity threshold and requires a close reason', async () => {
    const user = userEvent.setup();
    render(<ReplenishmentPage />);
    await screen.findByRole('grid', { name: 'ASIN补货运营决策矩阵' });

    await user.click(screen.getByRole('button', { name: '建议补货数量门槛: ≥30' }));
    await user.click(await screen.findByText('≥50'));
    const callsBeforeConfirm = apiMocks.dashboard.mock.calls.length;
    expect(apiMocks.dashboard).toHaveBeenCalledTimes(callsBeforeConfirm);
    await user.click(screen.getByRole('button', { name: '确定' }));
    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenLastCalledWith('replenishment', expect.objectContaining({ include_pricing: 'false', min_qty: '50' }), expect.any(AbortSignal)));
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
