import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage, { DashboardSectionCard, departmentMonitoringTabFromSearch } from './DashboardPage';
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
  const dailySales = key === '日均销量' || key === '可售天数';
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

const performanceFields = ['店铺', '在售SKU数量', '库存总数', '占用资金', '销售额贡献占比', '近7天日均订单', '近7天日均销售额（元）', '预估本月销售额（元）', '8月3日销量', '8月3日销售额（元）'];

describe('DepartmentMonitoring', () => {
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
    expect(screen.getAllByText('（前移7天）')).toHaveLength(4);
    expect(screen.queryByText('（万）')).not.toBeInTheDocument();
    expect(screen.getAllByText('考核销售额')).toHaveLength(1);
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


  it('expands the inline commission configuration for the matching person row key', async () => {
    const user = userEvent.setup();
    const commission = section(
      'commission',
      '2026-07 人员提成汇总',
      ['人员', '营业额', '毛利润', '毛利率', '提成预估', '配置状态'],
      [{ 人员: '陈千潼', 营业额: 10000, 毛利润: 3000, 毛利率: 0.3, 提成预估: 200, 配置状态: '已配置' }],
    );
    const { container } = render(<DashboardSectionCard
      initialSection={commission}
      dashboardPage="department"
      filters={{ month: '2026-07' }}
      compactSales={false}
      commissionConfig={{
        month: '2026-07',
        details: {
          陈千潼: {
            人员: '陈千潼',
            开发员配置: [{
              月份: '2026-07',
              开发员: '运营二十部-陈千潼',
              库存计提: 0,
              弃置: 0,
              职位提点: 0.1,
              缺失字段: [],
            }],
            部门费用率: [{
              月份: '2026-07',
              部门: '运营二十部',
              费用率: 0.095,
              缺失字段: [],
            }],
          },
        },
      }}
    />);
    expect(screen.queryByText('配置明细 · 陈千潼')).not.toBeInTheDocument();
    const expandButton = container.querySelector('.ant-table-row-expand-icon-collapsed');
    expect(expandButton).not.toBeNull();
    await user.click(expandButton as HTMLElement);
    expect(await screen.findByText('配置明细 · 陈千潼')).toBeInTheDocument();
    expect(screen.getByText('运营二十部-陈千潼')).toBeInTheDocument();
    expect(screen.getByText('运营二十部')).toBeInTheDocument();
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
        开发员: '甲', 销售额: 30000, 毛利润: 6000, 毛利率: 0.2, 中企销售额: 10000, 本土销售额: 20000,
        店铺明细: [
          { 店铺: 'YIP', 销售额: 20000, 毛利润: 3000, 毛利率: 0.15, 中企销售额: 0, 本土销售额: 20000 },
          { 店铺: 'TIS', 销售额: 10000, 毛利润: 1000, 毛利率: 0.1, 中企销售额: 10000, 本土销售额: 0 },
          { 店铺: 'ZXU', 销售额: 15000, 毛利润: 2000, 毛利率: 0.1333, 中企销售额: 15000, 本土销售额: 0 },
        ],
      }],
      updated_at: '2026-08-31T10:00:00+08:00',
    });
    const { container } = render(<DashboardPage page="department" />);
    await waitFor(() => expect(screen.getByText('考核销售额 = 中企销售额 + x × 本土销售额')).toBeInTheDocument());
    expect(await screen.findByText('甲')).toBeInTheDocument();
    expect(screen.getAllByText('3.00 万')).not.toHaveLength(0);
    expect(screen.getAllByText('毛利率')).toHaveLength(1);
    expect(screen.getAllByText('20.00%')).toHaveLength(2);
    expect(screen.getByText('考核销售额 = 中企销售额 + x × 本土销售额')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button').find(button => button.className.includes('ant-table-row-expand-icon'))!);
    expect(screen.getByText('YIP')).toBeInTheDocument();
    expect(screen.getByText('15.00%')).toBeInTheDocument();
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
        { 开发员: '付凯乐', 销售额: 10000, 毛利润: 5000, 毛利率: 0.5, 中企销售额: 10000, 本土销售额: 0, 店铺明细: [] },
        { 开发员: '陈千潼', 销售额: 90000, 毛利润: 45000, 毛利率: 0.5, 中企销售额: 90000, 本土销售额: 0, 店铺明细: [] },
      ],
      updated_at: '2026-08-31T10:00:00+08:00',
    });
    const { container } = render(<DashboardPage page="department" />);
    await waitFor(() => expect(screen.getByText('考核监控')).toBeInTheDocument());
    expect(await screen.findByText('付凯乐')).toBeInTheDocument();
    expect(screen.getByText('陈千潼')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '考核监控开发员筛选: 全部开发员' }));
    await user.click(screen.getByRole('checkbox', { name: '付凯乐' }));
    expect(Array.from(container.querySelectorAll('.department-assessment-table tbody tr td:first-child')).map(cell => cell.textContent?.trim()).sort()).toEqual(['付凯乐', '陈千潼']);
    expect(new URLSearchParams(window.location.search).get('developers')).toBeNull();
    await user.click(screen.getByRole('button', { name: '确定' }));
    await waitFor(() => {
      const developerCells = Array.from(container.querySelectorAll('.department-assessment-table tbody tr td:first-child')).map(cell => cell.textContent?.trim());
      expect(developerCells).toEqual(['付凯乐']);
    });
    expect(new URLSearchParams(window.location.search).get('developers')).toBe('付凯乐');
    expect(apiMocks.departmentAssessment).toHaveBeenCalledTimes(1);
  });
});
