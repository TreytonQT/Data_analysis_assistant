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
  departmentAssessment: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    api: {
      ...actual.api,
      dashboard: apiMocks.dashboard,
      dashboardSection: apiMocks.dashboardSection,
      departmentAssessment: apiMocks.departmentAssessment,
    },
  };
});

const amountFields = new Set([
  '销售额', '毛利润', '占用资金', '90天以上占用资金合计', '库存计提', '弃置费',
  '91-180天占用资金', '181-330天占用资金', '331-365天占用资金',
  '366-455天占用资金', '456天占用资金',
]);

function column(key: string): DashboardColumn {
  const percent = key.includes('毛利率') || key.includes('广告费占比');
  const dailySales = key === '日均销量';
  const text = ['SKU', 'ASIN', 'Rating', '开发员', '国家', '开售时间'].includes(key);
  const launchPrice = key.endsWith('开售价格');
  return {
    key,
    label: key,
    type: text ? 'string' : percent ? 'percent' : 'number',
    format: text ? 'text' : percent ? 'percent' : amountFields.has(key) ? 'amount' : dailySales || launchPrice ? 'number' : 'integer',
    precision: percent || amountFields.has(key) || dailySales || launchPrice ? 2 : 0,
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
  促销折扣: 10,
  开发员: '运营二十部-陈千潼',
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
  最近促销开始日期: '2026-08-01',
  最近促销截止日期: '2026-08-15',
  最近促销折扣: 20,
  日均销量: 5.678,
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

const performanceFields = ['店铺', '在售SKU数量', '库存总数', '占用资金', '销售额贡献占比', '近7天日均订单', '近7天日均销售额（元）', '预估本月销售额（元）', '8月3日销量', '8月3日销售额（元）'];

describe('DashboardDecisionMatrix', () => {
  beforeEach(() => {
    apiMocks.dashboard.mockReset();
    apiMocks.dashboardSection.mockReset();
    apiMocks.departmentAssessment.mockReset();
  });
  afterEach(() => {
    cleanup();
    window.localStorage.removeItem('department-assessment-local-ratio');
    window.history.replaceState({}, '', '/');
  });

  it('defines every source field exactly once and routes only the three requested sections', () => {
    expect(PRODUCT_MATRIX_FIELDS).toHaveLength(36);
    expect(new Set(PRODUCT_MATRIX_FIELDS).size).toBe(36);
    expect(LOW_MARGIN_MATRIX_FIELDS).toHaveLength(8);
    expect(new Set(LOW_MARGIN_MATRIX_FIELDS).size).toBe(8);
    expect(SLOW_MOVING_MATRIX_FIELDS).toHaveLength(21);
    expect(new Set(SLOW_MOVING_MATRIX_FIELDS).size).toBe(21);
    expect(dashboardMatrixKind('products', 'detail')).toBe('product-detail');
    expect(dashboardMatrixKind('products', 'low-margin')).toBe('low-margin');
    expect(dashboardMatrixKind('slow-moving', 'detail')).toBe('slow-moving');
    expect(dashboardMatrixKind('sales', 'stores')).toBeNull();
  });

  it('renders the 36-field product matrix with launch, promotion, developer, margin, ad-ratio and rating states', () => {
    const product = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [productRow]);
    const { container } = render(<DashboardDecisionMatrix kind="product-detail" section={product} />);

    expect(container.querySelector('table')).not.toBeInTheDocument();
    expect(screen.getByRole('grid', { name: '产品管理明细决策矩阵' })).toHaveAttribute('aria-colcount', '9');
    expect(screen.getByText('SKU-PRODUCT-001')).toBeInTheDocument();
    expect(screen.getByText('促销 -10%')).toHaveClass('dashboard-matrix-promotion');
    expect(screen.getByText('运营二十部-陈千潼')).toHaveClass('dashboard-matrix-developer');
    expect(screen.getByText('120(4.5)')).toHaveClass('rating-good');
    expect(screen.getByText('2026-08-03')).toBeInTheDocument();
    expect(screen.getByText('5.90')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-good')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-warning')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-low')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-country-matrix .tone-negative')).toBeInTheDocument();
    expect(screen.getByText('1.23 万')).toBeInTheDocument();
  });

  it('renders the shared SKU image preview and no-image placeholder in all three matrices', () => {
    const image = {
      url: 'https://cdn.example.com/SKU-1.jpg',
      inventory_sku: 'LOCAL-1',
      virtual_sku: 'SKU-PRODUCT-001',
    };
    const product = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [{ ...productRow, image }]);
    const low = section('low-margin', '低毛利率 SKU', LOW_MARGIN_MATRIX_FIELDS, [{ ...lowMarginRow, image }]);
    const slow = section('detail', '滞销 SKU 明细', SLOW_MOVING_MATRIX_FIELDS, [slowMovingRow]);
    const { container, rerender } = render(<DashboardDecisionMatrix kind="product-detail" section={product} />);

    expect(container.querySelector('.dashboard-matrix-image')).toHaveAttribute('src', image.url);
    expect(screen.getByAltText('SKU-PRODUCT-001库存图片')).toBeInTheDocument();

    rerender(<DashboardDecisionMatrix kind="low-margin" section={low} />);
    expect(container.querySelector('.dashboard-matrix-image')).toHaveAttribute('src', image.url);
    expect(screen.getByAltText('SKU-LOW-001库存图片')).toBeInTheDocument();

    rerender(<DashboardDecisionMatrix kind="slow-moving" section={slow} />);
    expect(screen.getByLabelText('SKU-SLOW-001暂无图片')).toBeInTheDocument();
    expect(container.querySelector('.dashboard-matrix-image')).not.toBeInTheDocument();
    expect(screen.getByText('最近促销：2026-08-01 至 2026-08-15 · -20%')).toBeInTheDocument();
    expect(container.querySelector('.slow-overview-daily strong')).toHaveTextContent('5.68');
  });

  it('renders open-ended and missing last-promotion states', () => {
    const openEnded = { ...slowMovingRow, 最近促销截止日期: null };
    const missing = { ...slowMovingRow, 最近促销开始日期: null, 最近促销截止日期: null, 最近促销折扣: null };
    const slow = section('detail', '滞销 SKU 明细', SLOW_MOVING_MATRIX_FIELDS, [openEnded, missing]);
    render(<DashboardDecisionMatrix kind="slow-moving" section={slow} />);

    expect(screen.getByText('最近促销：2026-08-01 起 · -20%')).toBeInTheDocument();
    expect(screen.getByText('最近促销：暂无记录')).toBeInTheDocument();
  });

  it('renders missing daily sales as a dash without changing the risk metrics', () => {
    const slow = section('detail', '滞销 SKU 明细', SLOW_MOVING_MATRIX_FIELDS, [{ ...slowMovingRow, 日均销量: null }]);
    const { container } = render(<DashboardDecisionMatrix kind="slow-moving" section={slow} />);

    expect(container.querySelector('.slow-overview-daily strong')).toHaveTextContent('-');
    expect(screen.getByText('90+库存')).toBeInTheDocument();
    expect(screen.getByText('150')).toBeInTheDocument();
  });

  it('distinguishes an unavailable promotion payload from an empty promotion record', () => {
    const legacyRow = Object.fromEntries(
      Object.entries(slowMovingRow).filter(([key]) => !key.startsWith('最近促销')),
    );
    const slow = section('detail', '滞销 SKU 明细', SLOW_MOVING_MATRIX_FIELDS, [legacyRow]);
    render(<DashboardDecisionMatrix kind="slow-moving" section={slow} />);

    expect(screen.getByText('最近促销：信息未加载')).toBeInTheDocument();
  });

  it('hides the promotion badge when a SKU is not currently promoted', () => {
    const product = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [{ ...productRow, 促销折扣: null }]);
    render(<DashboardDecisionMatrix kind="product-detail" section={product} />);

    expect(screen.queryByText(/促销 -/)).not.toBeInTheDocument();
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

    window.history.pushState({}, '', '/?page=products&developers=陈千潼&tab=low-margin');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(container.querySelector('.dashboard-section-low-margin')?.parentElement).not.toHaveAttribute('hidden'));
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('low-margin');
    expect(new URLSearchParams(window.location.search).get('developers')).toBe('陈千潼');
    await waitFor(() => {
      expect(container.querySelector('.dashboard-section-detail')?.parentElement).toHaveAttribute('hidden');
      expect(container.querySelector('.dashboard-section-low-margin')?.parentElement).not.toHaveAttribute('hidden');
    });

    window.history.replaceState({}, '', '/?page=products&developers=陈千潼&tab=detail');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => {
      expect(container.querySelector('.dashboard-section-detail')?.parentElement).not.toHaveAttribute('hidden');
      expect(container.querySelector('.dashboard-section-low-margin')?.parentElement).toHaveAttribute('hidden');
    });
  });

  it('switches department monitoring tabs, preserves month filter, and renders store performance', async () => {
    const user = userEvent.setup();
    const commission = section('commission', '2026-07 人员提成汇总', ['人员', '营业额'], [{ 人员: '陈千潼', 营业额: 100 }]);
    const developer = section('performance-0', '开发员业绩排行', performanceFields.map(field => field === '店铺' ? '开发员' : field), [{ 开发员: '陈千潼', 在售SKU数量: 2, 库存总数: 1234, 占用资金: 12345, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
    const department = section('performance-1', '部门业绩', performanceFields.map(field => field === '店铺' ? '部门' : field), [{ 部门: '运营二十部', 在售SKU数量: 2, 库存总数: 1234, 占用资金: 12345, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
    const stores = section('performance-2', '店铺业绩排行', performanceFields, [{ 店铺: 'AEU', 在售SKU数量: 1, 库存总数: 5678, 占用资金: 67890, 销售额贡献占比: 1, 近7天日均订单: 3, '近7天日均销售额（元）': 100, '预估本月销售额（元）': 200, '8月3日销量': 3, '8月3日销售额（元）': 100 }]);
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
    await waitFor(() => expect(screen.getByText('店铺业绩排行榜')).toBeInTheDocument());
    expect(departmentMonitoringTabFromSearch('?tab=unknown')).toBe('performance');
    expect(screen.getByText('店铺业绩排行榜')).toBeInTheDocument();
    expect(screen.getByText('AEU')).toBeInTheDocument();
    expect(screen.getAllByText('在售SKU数量')).toHaveLength(3);
    expect(screen.getAllByText('库存总数')).toHaveLength(3);
    expect(screen.getAllByText('占用资金')).toHaveLength(3);
    expect(screen.getAllByText('1,234')).toHaveLength(2);
    expect(screen.getAllByText('1.23 万')).toHaveLength(2);
    expect(screen.getByRole('img', { name: '开发员业绩排行全量数据概览图' })).toHaveAttribute(
      'viewBox',
      expect.stringMatching(/^0 0 1700 /),
    );
    expect(screen.getByRole('img', { name: '开发员业绩排行全量数据概览图' })).not.toHaveAttribute('style');
    expect(screen.queryByPlaceholderText('选择月份')).not.toBeInTheDocument();
    expect(container.querySelector('.dashboard-section-commission')?.parentElement).toHaveAttribute('hidden');

    window.history.pushState({}, '', '/?page=department&month=2026-07&tab=commission');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(container.querySelector('.filter-card')).toBeInTheDocument());
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('commission');
    expect(new URLSearchParams(window.location.search).get('month')).toBe('2026-07');
    await waitFor(() => expect(container.querySelector('.filter-card')).toBeInTheDocument());
    expect(container.querySelector('.dashboard-section-commission')?.parentElement).not.toHaveAttribute('hidden');
    expect(container.querySelector('.dashboard-section-performance-2')?.parentElement).toHaveAttribute('hidden');

    window.history.replaceState({}, '', '/?page=department&month=2026-07&tab=performance');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByText('店铺业绩排行榜')).toBeInTheDocument());
  });

  it('renders assessment monitoring with expandable stores and recalculates the local discount', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/?page=department&tab=assessment&month=2026-08');
    apiMocks.departmentAssessment.mockResolvedValue({
      title: '考核监控',
      months: ['2026-07', '2026-08'],
      selected_month: '2026-08',
      has_data: true,
      rows: [{
        开发员: '甲', 销售额: 30000, 中企销售额: 10000, 本土销售额: 20000,
        店铺明细: [
          { 店铺: 'YIP', 销售额: 20000, 中企销售额: 0, 本土销售额: 20000 },
          { 店铺: 'TIS', 销售额: 10000, 中企销售额: 10000, 本土销售额: 0 },
          { 店铺: 'ZXU', 销售额: 15000, 中企销售额: 15000, 本土销售额: 0 },
        ],
      }],
      updated_at: '2026-08-31T10:00:00+08:00',
    });
    const { container } = render(<DashboardPage page="department" />);
    await waitFor(() => expect(screen.getByText('考核销售额 = 中企销售额 + x × 本土销售额')).toBeInTheDocument());
    expect(await screen.findByText('甲')).toBeInTheDocument();
    expect(screen.getAllByText('3.00 万')).not.toHaveLength(0);
    expect(screen.getByText('考核销售额 = 中企销售额 + x × 本土销售额')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button').find(button => button.className.includes('ant-table-row-expand-icon'))!);
    expect(screen.getByText('YIP')).toBeInTheDocument();
    const storeRows = Array.from(container.querySelectorAll('tr.department-assessment-store-row'));
    expect(storeRows[0]).toHaveTextContent('YIP');
    expect(storeRows[0]).toHaveClass('department-assessment-store-row');
    const ratioInput = screen.getByRole('spinbutton', { name: '本土业绩折扣比例' });
    await user.clear(ratioInput);
    await user.type(ratioInput, '0.5');
    await ratioInput.blur();
    await waitFor(() => expect(screen.getAllByText('2.00 万')).not.toHaveLength(0));
    expect(Array.from(container.querySelectorAll('tr.department-assessment-store-row'))[0]).toHaveTextContent('ZXU');
    expect(localStorage.getItem('department-assessment-local-ratio')).toBe('0.5');
  });

  it('filters assessment monitoring by developer without requesting another report', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/?page=department&tab=assessment&month=2026-08');
    apiMocks.departmentAssessment.mockResolvedValue({
      title: '考核监控',
      months: ['2026-08'],
      selected_month: '2026-08',
      has_data: true,
      rows: [
        { 开发员: '付凯乐', 销售额: 10000, 中企销售额: 10000, 本土销售额: 0, 店铺明细: [] },
        { 开发员: '陈千潼', 销售额: 90000, 中企销售额: 90000, 本土销售额: 0, 店铺明细: [] },
      ],
      updated_at: '2026-08-31T10:00:00+08:00',
    });
    const { container } = render(<DashboardPage page="department" />);
    await waitFor(() => expect(screen.getByText('考核监控')).toBeInTheDocument());
    expect(await screen.findByText('付凯乐')).toBeInTheDocument();
    expect(screen.getByText('陈千潼')).toBeInTheDocument();
    const developerSelect = screen.getByRole('combobox', { name: '考核监控开发员筛选' });
    await user.click(developerSelect);
    await user.click(screen.getByText('付凯乐', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => {
      const developerCells = Array.from(container.querySelectorAll('.department-assessment-table tbody tr td:first-child')).map(cell => cell.textContent?.trim());
      expect(developerCells).toEqual(['付凯乐']);
    });
    expect(new URLSearchParams(window.location.search).get('developer')).toBe('付凯乐');
    expect(apiMocks.departmentAssessment).toHaveBeenCalledTimes(1);
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
    expect(ratingTone('0(0.0)')).toBe('rating-missing');
    expect(ratingTone('0')).toBe('rating-missing');
  });

  it('uses the gray rating state when the review count is zero', () => {
    const zeroRatingRow = { ...productRow, Rating: '0(0.0)' };
    const product = section('detail', '产品管理明细', PRODUCT_MATRIX_FIELDS, [zeroRatingRow]);
    render(<DashboardDecisionMatrix kind="product-detail" section={product} />);

    expect(screen.getByText('0(0.0)')).toHaveClass('rating-missing');
    expect(screen.getByText('0(0.0)')).not.toHaveClass('rating-danger');
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
