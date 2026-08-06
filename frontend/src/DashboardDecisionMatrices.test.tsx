import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage, { DashboardSectionCard, departmentMonitoringTabFromSearch, productManagementTabFromSearch } from './DashboardPage';
import {
  DashboardDecisionMatrix,
  LOW_MARGIN_MATRIX_FIELDS,
  PRODUCT_MATRIX_FIELDS,
  SLOW_MOVING_MATRIX_FIELDS,
  adRatioTone,
  dashboardMatrixKind,
  marginTone,
  ratingTone,
} from './DashboardDecisionMatrices';
import type { DashboardColumn, DashboardSection } from './api';

const apiMocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  dashboardSection: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    api: {
      ...actual.api,
      dashboard: apiMocks.dashboard,
      dashboardSection: apiMocks.dashboardSection,
    },
  };
});

const amountFields = new Set([
  '销售额', '毛利润', '90天以上占用资金合计', '库存计提', '弃置费',
  '91-180天占用资金', '181-330天占用资金', '331-365天占用资金',
  '366-455天占用资金', '456天占用资金',
]);

function column(key: string): DashboardColumn {
  const percent = key.includes('毛利率') || key.includes('广告费占比');
  const text = ['SKU', 'ASIN', 'Rating', '开发员', '国家', '开售时间'].includes(key);
  const launchPrice = key.endsWith('开售价格');
  return {
    key,
    label: key,
    type: text ? 'string' : percent ? 'percent' : 'number',
    format: text ? 'text' : percent ? 'percent' : amountFields.has(key) ? 'amount' : launchPrice ? 'number' : 'integer',
    precision: percent || amountFields.has(key) || launchPrice ? 2 : 0,
    sortable: true,
  };
}

function section(
  key: string,
  title: string,
  fields: readonly string[],
  rows: Record<string, unknown>[],
): DashboardSection {
  return {
    key,
    title,
    columns: fields.map(column),
    rows,
    page: 1,
    page_size: 50,
    total: rows.length,
    paginated: false,
    server_managed: true,
  };
}

const productRow = Object.fromEntries(PRODUCT_MATRIX_FIELDS.map((key, index) => [key, index + 1])) as Record<string, unknown>;
Object.assign(productRow, {
  SKU: 'SKU-PRODUCT-001',
  ASIN: 'B0PRODUCT01',
  Rating: '120(4.5)',
  开售时间: '2026-08-03',
  开售天数: 0,
  德国开售价格: 5.9,
  法国开售价格: 6.99,
  西班牙开售价格: 7.99,
  意大利开售价格: null,
  德国毛利率: 0.25,
  德国广告费占比: 0.08,
  法国毛利率: 0.15,
  法国广告费占比: 0.15,
  西班牙毛利率: 0.05,
  西班牙广告费占比: 0.25,
  意大利毛利率: -0.05,
  毛利率: 0.2,
  销售额: 12345,
  毛利润: 2345,
});

const lowMarginRow = {
  SKU: 'SKU-LOW-001',
  ASIN: 'B0LOW00001',
  开发员: '运营六部-陈千潼',
  国家: '德国',
  销量: 10,
  销售额: 10000,
  毛利润: -500,
  毛利率: -0.05,
};

const slowMovingRow = {
  SKU: 'SKU-SLOW-001',
  ASIN: 'B0SLOW0001',
  开发员: '运营六部-陈千潼',
  '90天以上库存数合计': 150,
  '90天以上占用资金合计': 12000,
  库存计提: 800,
  弃置费: 2000,
  '91-180天库存数': 1,
  '181-330天库存数': 2,
  '331-365天库存数': 3,
  '366-455天库存数': 4,
  '456天以上库存数': 5,
  '91-180天占用资金': 100,
  '181-330天占用资金': 200,
  '331-365天占用资金': 300,
  '366-455天占用资金': 400,
  '456天占用资金': 500,
};

const performanceFields = ['店铺', '在售SKU数量', '销售额贡献占比', '近7天日均订单', '近7天日均销售额（元）', '预估本月销售额（元）', '8月3日销量', '8月3日销售额（元）'];

describe('DashboardDecisionMatrix', () => {
  beforeEach(() => {
    apiMocks.dashboard.mockReset();
    apiMocks.dashboardSection.mockReset();
  });
  afterEach(() => {
    cleanup();
    window.history.replaceState({}, '', '/');
  });

  it('defines every source field exactly once and routes only the three requested sections', () => {
    expect(PRODUCT_MATRIX_FIELDS).toHaveLength(34);
    expect(new Set(PRODUCT_MATRIX_FIELDS).size).toBe(34);
    expect(LOW_MARGIN_MATRIX_FIELDS).toHaveLength(8);
    expect(new Set(LOW_MARGIN_MATRIX_FIELDS).size).toBe(8);
    expect(SLOW_MOVING_MATRIX_FIELDS).toHaveLength(17);
    expect(new Set(SLOW_MOVING_MATRIX_FIELDS).size).toBe(17);
    expect(dashboardMatrixKind('products', 'detail')).toBe('product-detail');
    expect(dashboardMatrixKind('products', 'low-margin')).toBe('low-margin');
    expect(dashboardMatrixKind('slow-moving', 'detail')).toBe('slow-moving');
    expect(dashboardMatrixKind('sales', 'stores')).toBeNull();
  });

  it('renders the 34-field product matrix with launch, margin, ad-ratio and rating states', () => {
    const product = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [productRow]);
    const { container } = render(<DashboardDecisionMatrix kind="product-detail" section={product} />);

    expect(container.querySelector('table')).not.toBeInTheDocument();
    expect(screen.getByRole('grid', { name: '产品管理明细决策矩阵' })).toHaveAttribute('aria-colcount', '9');
    expect(screen.getByText('SKU-PRODUCT-001')).toBeInTheDocument();
    expect(screen.getByText('120(4.5)')).toHaveClass('rating-good');
    expect(screen.getByText('2026-08-03')).toBeInTheDocument();
    expect(screen.getByText('5.90')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-good')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-warning')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-low')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-negative')).toBeInTheDocument();
    expect(screen.getByText('1.23 万')).toBeInTheDocument();
  });

  it('defaults product tabs to detail and keeps filters while switching and restoring history', async () => {
    const user = userEvent.setup();
    const detail = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [productRow]);
    const low = section('low-margin', '低毛利率 SKU', LOW_MARGIN_MATRIX_FIELDS, [lowMarginRow]);
    window.history.replaceState({}, '', '/?page=products&developers=陈千潼');
    apiMocks.dashboard.mockResolvedValue({
      title: '产品管理',
      has_data: true,
      filters: { developers: ['陈千潼'] },
      selected: { developers: ['陈千潼'] },
      metrics: [],
      sections: [low, detail],
      updated_at: '2026-08-03T12:00:00+08:00',
    });

    const { container } = render(<DashboardPage page="products" />);
    await waitFor(() => expect(apiMocks.dashboard).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector('.dashboard-section-detail')).toBeInTheDocument());

    const detailPane = container.querySelector('.dashboard-section-detail')?.parentElement;
    const lowPane = container.querySelector('.dashboard-section-low-margin')?.parentElement;
    expect(detailPane).not.toHaveAttribute('hidden');
    expect(lowPane).toHaveAttribute('hidden');
    expect(productManagementTabFromSearch('?tab=unknown')).toBe('detail');

    await user.click(screen.getByRole('tab', { name: '低毛利率 SKU' }));
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('low-margin');
    expect(new URLSearchParams(window.location.search).get('developers')).toBe('陈千潼');
    expect(detailPane).toHaveAttribute('hidden');
    expect(lowPane).not.toHaveAttribute('hidden');

    window.history.replaceState({}, '', '/?page=products&developers=陈千潼&tab=detail');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByRole('tab', { name: '产品管理明细' })).toHaveAttribute('aria-selected', 'true'));
    await waitFor(() => {
      expect(container.querySelector('.dashboard-section-detail')?.parentElement).not.toHaveAttribute('hidden');
      expect(container.querySelector('.dashboard-section-low-margin')?.parentElement).toHaveAttribute('hidden');
    });
  });

  it('switches department monitoring tabs, preserves month filter, and renders store performance', async () => {
    const user = userEvent.setup();
    const commission = section('commission', '2026-07 人员提成汇总', ['人员', '营业额'], [{ 人员: '陈千潼', 营业额: 100 }]);
    const developer = section('performance-0', '开发员业绩排行', performanceFields.map(field => field === '店铺' ? '开发员' : field), [{ 开发员: '陈千潼', 在售SKU数量: 2, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
    const department = section('performance-1', '部门业绩', performanceFields.map(field => field === '店铺' ? '部门' : field), [{ 部门: '运营二十部', 在售SKU数量: 2, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
    const stores = section('performance-2', '店铺业绩排行', performanceFields, [{ 店铺: 'AEU', 在售SKU数量: 1, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
    window.history.replaceState({}, '', '/?page=department&month=2026-07');
    apiMocks.dashboard.mockResolvedValue({
      title: '部门监控',
      has_data: true,
      filters: { months: ['2026-07'] },
      selected: { month: '2026-07' },
      sections: [commission, developer, department, stores],
      updated_at: '2026-08-04T12:00:00+08:00',
    });

    const { container } = render(<DashboardPage page="department" />);
    await waitFor(() => expect(screen.getByRole('tab', { name: '业绩监控' })).toHaveAttribute('aria-selected', 'true'));
    expect(departmentMonitoringTabFromSearch('?tab=unknown')).toBe('performance');
    expect(screen.getByText('店铺业绩排行榜')).toBeInTheDocument();
    expect(screen.getByText('AEU')).toBeInTheDocument();
    expect(screen.getAllByText('在售SKU数量')).toHaveLength(3);
    expect(screen.queryByPlaceholderText('选择月份')).not.toBeInTheDocument();
    expect(container.querySelector('.dashboard-section-commission')?.parentElement).toHaveAttribute('hidden');

    await user.click(screen.getByRole('tab', { name: '提成监控' }));
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('commission');
    expect(new URLSearchParams(window.location.search).get('month')).toBe('2026-07');
    await waitFor(() => expect(container.querySelector('.filter-card')).toBeInTheDocument());
    expect(container.querySelector('.dashboard-section-commission')?.parentElement).not.toHaveAttribute('hidden');
    expect(container.querySelector('.dashboard-section-performance-2')?.parentElement).toHaveAttribute('hidden');

    window.history.replaceState({}, '', '/?page=department&month=2026-07&tab=performance');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByRole('tab', { name: '业绩监控' })).toHaveAttribute('aria-selected', 'true'));
  });

  it('renders low-margin and slow-moving rows without native tables', () => {
    const low = section('low-margin', '低毛利率 SKU', LOW_MARGIN_MATRIX_FIELDS, [lowMarginRow]);
    const slow = section('detail', '滞销 SKU 明细', SLOW_MOVING_MATRIX_FIELDS, [slowMovingRow]);
    const { container, rerender } = render(<DashboardDecisionMatrix kind="low-margin" section={low} />);

    expect(screen.getByRole('grid', { name: '低毛利率 SKU决策矩阵' })).toHaveAttribute('aria-colcount', '4');
    expect(screen.getByText('负毛利')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-margin-risk.tone-negative')).toHaveTextContent('-5%');

    rerender(<DashboardDecisionMatrix kind="slow-moving" section={slow} />);
    expect(screen.getByRole('grid', { name: '滞销 SKU 明细决策矩阵' })).toHaveAttribute('aria-colcount', '4');
    expect(container.querySelectorAll('.dashboard-aging-grid .aging-level-5')).toHaveLength(2);
    expect(screen.getAllByText('456+')).toHaveLength(2);
    expect(container.querySelector('table')).not.toBeInTheDocument();
  });

  it('keeps color boundaries explicit', () => {
    expect(marginTone(0.2)).toBe('tone-good');
    expect(marginTone(0.1)).toBe('tone-warning');
    expect(marginTone(0)).toBe('tone-low');
    expect(marginTone(-0.01)).toBe('tone-negative');
    expect(adRatioTone(0.1)).toBe('tone-good');
    expect(adRatioTone(0.2)).toBe('tone-warning');
    expect(adRatioTone(0.201)).toBe('tone-negative');
    expect(ratingTone('10(4.3)')).toBe('rating-good');
    expect(ratingTone('10(3.5)')).toBe('rating-warning');
    expect(ratingTone('10(3.4)')).toBe('rating-danger');
  });

  it('uses server-side sorting and keeps the same export query', async () => {
    const user = userEvent.setup();
    const initial = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [productRow]);
    initial.total = 4568;
    initial.paginated = true;
    apiMocks.dashboardSection.mockResolvedValue(initial);

    render(<DashboardSectionCard
      initialSection={initial}
      dashboardPage="products"
      filters={{ developers: '陈千潼' }}
      compactSales={false}
    />);

    const sortField = screen.getByRole('combobox', { name: '产品管理明细排序字段' });
    await user.click(sortField);
    await user.type(sortField, '30天销量');
    await user.click(await screen.findByTitle('30天销量'));
    await waitFor(() => expect(apiMocks.dashboardSection).toHaveBeenCalledWith(
      'products',
      'detail',
      {
        developers: '陈千潼',
        page: '1',
        page_size: '50',
        sort_by: '30天销量',
        sort_order: 'desc',
      },
      expect.any(AbortSignal),
    ));

    const exportLink = screen.getByRole('link', { name: /导出全部 CSV/ });
    await waitFor(() => expect(exportLink).toHaveAttribute(
      'href',
      expect.stringContaining('sort_by=30%E5%A4%A9%E9%94%80%E9%87%8F'),
    ));
    await user.click(screen.getByRole('button', { name: '产品管理明细排序方向' }));
    await waitFor(() => expect(apiMocks.dashboardSection).toHaveBeenLastCalledWith(
      'products',
      'detail',
      expect.objectContaining({ sort_order: 'asc', page: '1' }),
      expect.any(AbortSignal),
    ));
  });
});
