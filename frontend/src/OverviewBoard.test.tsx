import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DashboardPage from './DashboardPage';

const apiMocks = vi.hoisted(() => ({ dashboard: vi.fn(), dashboardSection: vi.fn() }));
vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const makeData = () => ({
  title: '经营首页', has_data: true, filters: {}, selected: {},
  metrics: [
    { name: '销售额', value: 10000, format: 'amount' },
    { name: '销量', value: 0, format: 'integer' },
    { name: '毛利润', value: null, format: 'amount' },
    { name: '毛利率', value: 0, format: 'percent' },
    { name: '自定义指标', value: 7, format: 'integer' },
  ],
  sections: [
    { key: 'stores', title: '店铺分析', rows: [{ 店铺: 'DE-01', 销售额: 10000 }], columns: [{ key: '店铺', label: '店铺', type: 'string' }, { key: '销售额', label: '销售额', format: 'amount' }] },
    { key: 'developers', title: '开发员分析', server_managed: true, total: 1, page: 1, page_size: 50, rows: [{ 开发员: '甲', 销售额: 10000 }], columns: [{ key: '开发员', label: '开发员', type: 'string' }, { key: '销售额', label: '销售额', format: 'amount' }], chart: { x: '开发员', series: [{ key: '销售额', label: '销售额', format: 'amount' }] } },
    { key: 'alerts', title: '异常预警', rows: [{ 原因: '待检查的异常' }], columns: [{ key: '原因', label: '原因', type: 'string' }] },
    { key: 'custom', title: '新增配置区块', rows: [{ 字段: '保留的自定义内容' }], columns: [{ key: '字段', label: '字段', type: 'string' }] },
  ],
});

afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState({}, '', '/'); });

describe('overview business layout', () => {
  it('keeps configured metrics, actual zeroes and missing values distinct', async () => {
    apiMocks.dashboard.mockResolvedValue(makeData());
    render(<DashboardPage page="overview" />);
    await screen.findByText('利润表现');
    const sales = document.querySelector('.overview-sales-metrics')!;
    expect(sales).toHaveTextContent('1.00 万');
    expect(sales).toHaveTextContent('销量0');
    const profit = document.querySelector('.overview-finance-card')!;
    expect(profit).toHaveTextContent('毛利润-');
    expect(profit).toHaveTextContent('毛利率0%');
    expect(screen.getByText('自定义指标')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.queryByText('广告投入')).not.toBeInTheDocument();
  });

  it('retains all sections, exports and table drafts when moving between detail tabs', async () => {
    apiMocks.dashboard.mockResolvedValue(makeData());
    render(<DashboardPage page="overview" />);
    await screen.findByText('DE-01');
    fireEvent.click(screen.getByRole('button', { name: '查看明细' }));
    const developerPanel = screen.getByRole('tabpanel');
    const search = within(developerPanel).getByPlaceholderText('搜索当前表格');
    fireEvent.change(search, { target: { value: '尚未提交' } });
    expect(within(developerPanel).getByRole('link', { name: /导出筛选结果/ })).toHaveAttribute('href', expect.stringContaining('/api/dashboard/overview/sections/developers/export.csv'));
    fireEvent.click(screen.getByRole('tab', { name: '异常预警' }));
    await screen.findByText('待检查的异常');
    fireEvent.click(screen.getByRole('tab', { name: '新增配置区块' }));
    await screen.findByText('保留的自定义内容');
    fireEvent.click(screen.getByRole('tab', { name: '开发员分析' }));
    await waitFor(() => expect(screen.getByPlaceholderText('搜索当前表格')).toHaveValue('尚未提交'));
    expect(apiMocks.dashboard).toHaveBeenCalledTimes(1);
    expect(apiMocks.dashboardSection).not.toHaveBeenCalled();
  });
});
