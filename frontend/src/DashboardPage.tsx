import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Input, Pagination, Select, Skeleton, Space, Statistic, Table, Tabs, Typography } from 'antd';
import { DownloadOutlined, FilterOutlined, ReloadOutlined } from '@ant-design/icons';
import type { TableProps } from 'antd';
import { api, type DashboardChartSeries, type DashboardPayload, type DashboardSection } from './api';
import { DashboardDecisionMatrix, dashboardMatrixKind } from './DashboardDecisionMatrices';

const pageDescriptions: Record<string, string> = {
  overview: '销售、利润、提成与经营指标总览', sales: '按店铺、产品等级和日期对比分析销量与库存',
  'slow-moving': '识别高库龄库存、占用资金、库存计提与弃置费', products: '汇总产品销量、库存、毛利和 Rating',
  department: '部门与开发员业绩、人员提成汇总', replenishment: '结合库存、销量、毛利和 Rating 计算补货建议',
};
export type ProductManagementTab = 'detail' | 'low-margin';

export function productManagementTabFromSearch(search: string): ProductManagementTab {
  return new URLSearchParams(search).get('tab') === 'low-margin' ? 'low-margin' : 'detail';
}
export type DepartmentMonitoringTab = 'performance' | 'commission';

export function departmentMonitoringTabFromSearch(search: string): DepartmentMonitoringTab {
  return new URLSearchParams(search).get('tab') === 'commission' ? 'commission' : 'performance';
}

type ValueMeta = { format?: string; type?: string; unit?: string; precision?: number };
type SectionQuery = { page: number; pageSize: number; search: string; sortBy?: string; sortOrder?: 'asc' | 'desc' };
const filterKeys = ['developers', 'months', 'month', 'departments', 'store_types', 'threshold'] as const;
const amountNamePattern = /(销售额|营业额|毛利|利润|广告费|成本|货值|提成|计提|弃置费|占用资金|金额|费用|收入|支出)/;

function isPercentField(name = '', meta: ValueMeta = {}) {
  return ['百分比', 'percent', 'percentage'].includes(meta.format || '') || meta.type === 'percent' || /(占比|率|率目标|提点|完成率)$/.test(name);
}

function isAmountField(name = '', meta: ValueMeta = {}) {
  if (isPercentField(name, meta)) return false;
  const unit = (meta.unit || '').replaceAll(' ', '');
  return ['金额', 'amount', 'currency'].includes(meta.format || '') || meta.type === 'currency' || ['元', '人民币元', '万', '万元'].includes(unit) || amountNamePattern.test(name);
}

function amountInWan(value: number) {
  return (value / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function displayLabel(name: string, meta: ValueMeta = {}) {
  if (!isAmountField(name, meta)) return name;
  return name.replace(/（元）|\(元\)/g, '（万）');
}

function formattedValue(value: unknown, meta: ValueMeta = {}, name = '') {
  if (value === null || value === undefined || value === '') return '-';
  const numericFormat = ['数值', 'number', '整数', 'integer', '百分比', 'percent', 'percentage', '金额', 'amount', 'currency'].includes(meta.format || '');
  if (meta.format === 'text' || (meta.type === 'string' && !numericFormat)) return String(value);
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const defaultPrecision = meta.format === 'integer' || meta.format === '整数' || meta.type === 'integer' ? 0 : 2;
  const configuredPrecision = Number(meta.precision);
  const precision = Math.min(2, Math.max(0, Number.isFinite(configuredPrecision) ? Math.trunc(configuredPrecision) : defaultPrecision));
  if (isPercentField(name, meta)) return `${(numeric * 100).toLocaleString('zh-CN', { maximumFractionDigits: precision })}${meta.unit || '%'}`;
  if (isAmountField(name, meta)) return `${amountInWan(numeric)} 万`;
  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: precision })}${meta.unit ? ` ${meta.unit}` : ''}`;
}

function columnKeys(section: DashboardSection) {
  return section.columns.map(column => column.key);
}

function exportSection(section: DashboardSection) {
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const csv = `\ufeff${section.columns.map(column => escape(column.label)).join(',')}\n${section.rows.map(row => section.columns.map(column => escape(row[column.key])).join(',')).join('\n')}`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = `${section.title}.csv`; link.click(); URL.revokeObjectURL(url);
}

function MiniChart({ section }: { section: DashboardSection }) {
  if (!section.chart || !section.rows.length) return null;
  const chart = section.chart;
  const yesterday = chart.series.find(series => series.key === '昨日订单') || (columnKeys(section).includes('昨日订单') ? { key: '昨日订单', label: '昨日订单', format: 'integer' } : undefined);
  const average = chart.series.find(series => series.key === '30天日均') || (columnKeys(section).includes('30天日均') ? { key: '30天日均', label: '30 天日均销量' } : undefined);
  if (yesterday && average) return <StoreSalesCharts rows={section.rows} xKey={chart.x} yesterday={yesterday} average={average} />;
  const series = chart.series[0];
  if (!series) return null;
  const rows = section.rows.slice(0, 15).filter(row => Number.isFinite(Number(row[series.key])));
  if (!rows.length) return null;
  if (chart.kind === 'line') return <LineChart rows={rows} xKey={chart.x} series={series} />;
  const maximum = Math.max(...rows.map(row => Math.abs(Number(row[series.key]))), 1);
  return <div className="mini-chart">{rows.map((row, index) => <div className="mini-chart-row" key={`${String(row[chart.x])}-${index}`}><span title={String(row[chart.x])}>{String(row[chart.x])}</span><div><i style={{ width: `${Math.max(2, Math.abs(Number(row[series.key])) / maximum * 100)}%` }} /></div><b>{formattedValue(row[series.key], series, series.label || series.key)}</b></div>)}</div>;
}

function StoreSalesCharts({ rows, xKey, yesterday, average }: { rows: Record<string, unknown>[]; xKey: string; yesterday: DashboardChartSeries; average: DashboardChartSeries }) {
  const yesterdayKey = yesterday.key; const averageKey = average.key;
  const chartRows = rows.filter(row => Number.isFinite(Number(row[yesterdayKey])) || Number.isFinite(Number(row[averageKey])));
  if (!chartRows.length) return <Typography.Text type="secondary">暂无店铺销量数据</Typography.Text>;
  const width = 1200; const height = 340; const left = 58; const right = 20; const top = 40; const bottom = 70;
  const yesterdayValues = chartRows.map(row => Number(row[yesterdayKey]) || 0); const averageValues = chartRows.map(row => Number(row[averageKey]) || 0);
  const maximum = Math.max(...yesterdayValues, ...averageValues, 1); const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const step = plotWidth / chartRows.length; const barWidth = Math.max(4, Math.min(26, step * 0.32)); const groupGap = Math.max(2, Math.min(6, step * 0.06));
  const ticks = Array.from({ length: 4 }, (_, index) => maximum * (3 - index) / 3);
  return <div className="store-chart-grid"><section className="store-bar-chart"><div className="store-bar-chart-header"><div className="store-bar-chart-title">店铺销量对比</div><div className="store-chart-legend"><span><i className="store-chart-legend-yesterday" />{yesterday.label || yesterday.key}</span><span><i className="store-chart-legend-average" />{average.label || average.key}</span></div></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="店铺销量分组柱状图">
    {ticks.map(value => { const y = top + (maximum - value) / maximum * plotHeight; return <g key={value}><line className="store-chart-gridline" x1={left} x2={width - right} y1={y} y2={y} /><text className="store-chart-axis" x={left - 8} y={y + 4} textAnchor="end">{formattedValue(value)}</text></g>; })}
    {chartRows.map((row, index) => { const yesterdayValue = yesterdayValues[index]; const averageValue = averageValues[index]; const groupWidth = barWidth * 2 + groupGap; const groupX = left + index * step + (step - groupWidth) / 2; const baseline = top + plotHeight; const yesterdayHeight = yesterdayValue / maximum * plotHeight; const averageHeight = averageValue / maximum * plotHeight; const yesterdayY = baseline - yesterdayHeight; const averageY = baseline - averageHeight; return <g key={`${String(row[xKey])}-${index}`}><title>{`${String(row[xKey])}：${yesterday.label || yesterday.key} ${formattedValue(yesterdayValue, yesterday)}，${average.label || average.key} ${formattedValue(averageValue, average)}`}</title><rect className="store-chart-bar store-chart-bar-yesterday" x={groupX} y={yesterdayY} width={barWidth} height={Math.max(yesterdayValue ? 2 : 0, yesterdayHeight)} rx="2" /><rect className="store-chart-bar store-chart-bar-average" x={groupX + barWidth + groupGap} y={averageY} width={barWidth} height={Math.max(averageValue ? 2 : 0, averageHeight)} rx="2" /><text className="store-chart-value" x={groupX + barWidth / 2} y={Math.max(top + 11, yesterdayY - 6)} textAnchor="middle">{formattedValue(yesterdayValue, yesterday)}</text><text className="store-chart-value store-chart-value-average" x={groupX + barWidth + groupGap + barWidth / 2} y={Math.max(top + 11, averageY - 6)} textAnchor="middle">{formattedValue(averageValue, average)}</text><text className="store-chart-axis" x={left + index * step + step / 2} y={height - bottom + 18} textAnchor="end" transform={`rotate(-38 ${left + index * step + step / 2} ${height - bottom + 18})`}>{String(row[xKey])}</text></g>; })}
  </svg></section></div>;
}

function performanceValue(column: string, value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '';
  if (column === '销售额贡献占比') return `${(numeric * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
  if (isAmountField(column)) return `${amountInWan(numeric)} 万`;
  if (column === '在售SKU数量' || column === '库存总数' || column.endsWith('销量') || column === '近7天日均订单') {
    return numeric.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  }
  return numeric.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

function PerformanceOverviewImage({ section }: { section: DashboardSection }) {
  const titleHeight = 44; const dateHeaderHeight = 30; const subHeaderHeight = 32; const headerHeight = titleHeight + dateHeaderHeight + subHeaderHeight; const rowHeight = 36;
  const keys = columnKeys(section);
  const labelColumn = keys.includes('店铺') ? '店铺' : keys.includes('部门') ? '部门' : '开发员';
  const fixedColumns = [labelColumn, '在售SKU数量', '库存总数', '占用资金', '销售额贡献占比', '近7天日均订单', '近7天日均销售额（元）', '预估本月销售额（元）'];
  const fixedLabels = [[labelColumn], ['在售SKU数量'], ['库存总数'], ['占用资金', '（万）'], ['营业额', '贡献占比'], ['近7天', '日均订单'], ['近7天日均销售额', '（万）'], ['预估月度销售额', '（万）']];
  const fixedWidths = [90, 105, 100, 110, 110, 110, 130, 135];
  const fixedPositions = fixedWidths.reduce<number[]>((values, value) => [...values, values[values.length - 1] + value], [0]).slice(0, -1);
  const fixedWidth = fixedWidths.reduce((sum, value) => sum + value, 0);
  const dateLabels = keys.filter(column => /^\d+月\d+日销量$/.test(column)).map(column => column.replace('销量', ''));
  const width = 1700;
  const dailyWidth = (width - fixedWidth) / Math.max(dateLabels.length * 2, 1); const height = headerHeight + section.rows.length * rowHeight;
  const boardTitle = labelColumn === '店铺' ? '店铺业绩排行榜' : labelColumn === '开发员' ? '开发员业绩排行榜' : '部门业绩排行榜';
  return <div className="performance-overview-image"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${section.title}全量数据概览图`}>
    <rect className="performance-image-bg" width={width} height={height} />
    <rect className="performance-image-title" width={width} height={titleHeight} /><text className="performance-image-title-text" x={width / 2} y="29" textAnchor="middle">{boardTitle}</text>
    <rect className="performance-image-header" y={titleHeight} width={width} height={dateHeaderHeight + subHeaderHeight} />
    {fixedColumns.map((column, index) => <g key={column}><line className="performance-image-line" x1={fixedPositions[index]} x2={fixedPositions[index]} y1={titleHeight} y2={height} />{fixedLabels[index].map((line, lineIndex) => <text className="performance-compact-header-text" key={line} x={fixedPositions[index] + fixedWidths[index] / 2} y={fixedLabels[index].length === 1 ? titleHeight + 38 : titleHeight + 27 + lineIndex * 18} textAnchor="middle">{line}</text>)}</g>)}
    {dateLabels.map((date, dateIndex) => { const x = fixedWidth + dateIndex * dailyWidth * 2; return <g key={date}><line className="performance-image-line" x1={x} x2={x} y1={titleHeight} y2={height} /><text className="performance-date-header-text" x={x + dailyWidth} y={titleHeight + 21} textAnchor="middle">{date}</text><line className="performance-image-line" x1={x} x2={x + dailyWidth * 2} y1={titleHeight + dateHeaderHeight} y2={titleHeight + dateHeaderHeight} /><line className="performance-image-line" x1={x + dailyWidth} x2={x + dailyWidth} y1={titleHeight + dateHeaderHeight} y2={height} /><text className="performance-sub-header-text" x={x + dailyWidth / 2} y={titleHeight + dateHeaderHeight + 21} textAnchor="middle">销量</text><text className="performance-sub-header-text" x={x + dailyWidth * 1.5} y={titleHeight + dateHeaderHeight + 16} textAnchor="middle">销售额</text><text className="performance-sub-header-unit" x={x + dailyWidth * 1.5} y={titleHeight + dateHeaderHeight + 28} textAnchor="middle">（万）</text></g>; })}
    {section.rows.map((row, rowIndex) => { const y = headerHeight + rowIndex * rowHeight; const isTotal = String(row[labelColumn]) === '合计'; return <g key={rowIndex}><rect className={isTotal ? 'performance-image-row-highlight' : 'performance-image-row'} x="0" y={y} width={width} height={rowHeight} />{!isTotal && <><rect className="performance-image-share-cell" x={fixedPositions[4]} y={y} width={fixedWidths[4]} height={rowHeight} /><rect className="performance-image-key-cell" x={fixedPositions[5]} y={y} width={fixedWidths[5] + fixedWidths[6] + fixedWidths[7]} height={rowHeight} /></>}{fixedColumns.map((column, index) => <text className={isTotal ? 'performance-image-total-cell' : 'performance-compact-cell'} key={column} x={fixedPositions[index] + fixedWidths[index] / 2} y={y + 24} textAnchor="middle">{column === labelColumn ? String(row[column] ?? '') : performanceValue(column, row[column])}</text>)}{dateLabels.map((date, dateIndex) => { const x = fixedWidth + dateIndex * dailyWidth * 2; return <g key={date}><text className={isTotal ? 'performance-image-total-cell' : 'performance-compact-cell'} x={x + dailyWidth / 2} y={y + 24} textAnchor="middle">{performanceValue(`${date}销量`, row[`${date}销量`])}</text><text className={isTotal ? 'performance-image-total-cell' : 'performance-compact-cell'} x={x + dailyWidth * 1.5} y={y + 24} textAnchor="middle">{performanceValue(`${date}销售额（元）`, row[`${date}销售额（元）`])}</text></g>; })}<line className="performance-image-line" x1="0" x2={width} y1={y + rowHeight} y2={y + rowHeight} /></g>; })}
    <line className="performance-image-line" x1="0" x2={width} y1={titleHeight} y2={titleHeight} /><line className="performance-image-line" x1="0" x2={width} y1={headerHeight} y2={headerHeight} /><rect className="performance-image-border" width={width} height={height} />
  </svg></div>;
}

function LineChart({ rows, xKey, series }: { rows: Record<string, unknown>[]; xKey: string; series: DashboardChartSeries }) {
  if (!rows.length) return null;
  const width = 920; const height = 280; const left = 76; const right = 24; const top = 22; const bottom = 46;
  const values = rows.map(row => Number(row[series.key])); const minimum = Math.min(0, ...values); const maximum = Math.max(...values, 1); const range = maximum - minimum || 1;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const point = (value: number, index: number) => ({ x: left + (rows.length === 1 ? plotWidth / 2 : index * plotWidth / (rows.length - 1)), y: top + (maximum - value) / range * plotHeight });
  const points = values.map(point); const path = points.map((item, index) => `${index ? 'L' : 'M'} ${item.x} ${item.y}`).join(' ');
  const ticks = Array.from({ length: 5 }, (_, index) => minimum + range * (4 - index) / 4);
  return <div className="line-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${series.label || series.key}月度趋势折线图`}>
    {ticks.map(value => { const y = top + (maximum - value) / range * plotHeight; return <g key={value}><line className="line-chart-grid" x1={left} x2={width - right} y1={y} y2={y} /><text className="line-chart-axis" x={left - 12} y={y + 4} textAnchor="end">{formattedValue(value, series, series.label || series.key)}</text></g>; })}
    <line className="line-chart-axis-line" x1={left} x2={left} y1={top} y2={height - bottom} /><line className="line-chart-axis-line" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
    <path className="line-chart-path" d={path} />
    {points.map((item, index) => <g key={`${String(rows[index][xKey])}-${index}`}><circle className="line-chart-point" cx={item.x} cy={item.y} r="4" /><text className="line-chart-value" x={item.x} y={item.y - 10} textAnchor="middle">{formattedValue(values[index], series, series.label || series.key)}</text><text className="line-chart-axis" x={item.x} y={height - 18} textAnchor="middle">{String(rows[index][xKey])}</text></g>)}
  </svg></div>;
}

function compareValues(left: unknown, right: unknown) {
  const a = Number(left); const b = Number(right);
  return Number.isFinite(a) && Number.isFinite(b) ? a - b : String(left ?? '').localeCompare(String(right ?? ''), 'zh-CN');
}

function sectionExportUrl(page: string, section: string, filters: Record<string, string>, query: SectionQuery) {
  const params = new URLSearchParams(filters);
  if (query.search) params.set('search', query.search);
  if (query.sortBy) params.set('sort_by', query.sortBy);
  if (query.sortOrder) params.set('sort_order', query.sortOrder);
  const suffix = params.toString();
  return `/api/dashboard/${encodeURIComponent(page)}/sections/${encodeURIComponent(section)}/export.csv${suffix ? `?${suffix}` : ''}`;
}

export function DashboardSectionCard({ initialSection, dashboardPage, filters, compactSales }: { initialSection: DashboardSection; dashboardPage: string; filters: Record<string, string>; compactSales: boolean }) {
  const performance = initialSection.title === '开发员业绩排行' || initialSection.title === '部门业绩' || initialSection.title === '店铺业绩排行';
  const remote = Boolean(initialSection.server_managed) && !performance;
  const matrixKind = dashboardMatrixKind(dashboardPage, initialSection.key);
  const [section, setSection] = useState(initialSection);
  const [query, setQuery] = useState<SectionQuery>({ page: initialSection.page || 1, pageSize: initialSection.page_size || 50, search: '' });
  const [searchDraft, setSearchDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | undefined>(undefined);
  const requestRef = useRef(0);

  useEffect(() => {
    abortRef.current?.abort(); requestRef.current += 1;
    setSection(initialSection);
    setQuery({ page: initialSection.page || 1, pageSize: initialSection.page_size || 50, search: '' });
    setSearchDraft(''); setLoading(false); setError('');
  }, [initialSection]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const loadSection = async (nextQuery: SectionQuery) => {
    if (!remote) return;
    abortRef.current?.abort();
    const controller = new AbortController(); abortRef.current = controller;
    const requestId = ++requestRef.current;
    setLoading(true); setError(''); setSection(current => ({ ...current, rows: [] })); setQuery(nextQuery);
    const params: Record<string, string> = { ...filters, page: String(nextQuery.page), page_size: String(nextQuery.pageSize) };
    if (nextQuery.search) params.search = nextQuery.search;
    if (nextQuery.sortBy) params.sort_by = nextQuery.sortBy;
    if (nextQuery.sortOrder) params.sort_order = nextQuery.sortOrder;
    try {
      const result = await api.dashboardSection(dashboardPage, initialSection.key, params, controller.signal);
      if (requestId === requestRef.current) setSection(result);
    } catch (loadError) {
      if (controller.signal.aborted) return;
      if (requestId === requestRef.current) setError(loadError instanceof Error ? loadError.message : '表格加载失败');
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  };

  const tableColumns: TableProps<Record<string, unknown>>['columns'] = section.columns.map(column => ({
    title: displayLabel(column.label, column),
    dataIndex: column.key,
    key: column.key,
    ellipsis: true,
    render: value => formattedValue(value, column, column.label),
    sorter: remote ? column.sortable !== false : column.sortable === false ? undefined : (left, right) => compareValues(left[column.key], right[column.key]),
    sortOrder: query.sortBy === column.key && query.sortOrder ? query.sortOrder === 'asc' ? 'ascend' : 'descend' : undefined,
  }));
  const handleTableChange: TableProps<Record<string, unknown>>['onChange'] = (pagination, _filters, sorter, extra) => {
    if (!remote) return;
    const activeSorter = Array.isArray(sorter) ? sorter[0] : sorter;
    const sorterKey = activeSorter?.columnKey ?? activeSorter?.field;
    const sortBy = activeSorter?.order && (typeof sorterKey === 'string' || typeof sorterKey === 'number') ? String(sorterKey) : undefined;
    const sortOrder = activeSorter?.order === 'ascend' ? 'asc' : activeSorter?.order === 'descend' ? 'desc' : undefined;
    void loadSection({ page: extra.action === 'sort' ? 1 : pagination.current || 1, pageSize: pagination.pageSize || query.pageSize, search: query.search, sortBy, sortOrder });
  };
  const pagination = section.key === 'stores' && !remote ? false : remote ? {
    current: query.page, pageSize: query.pageSize, total: section.total || 0,
    showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100, 200], showTotal: (total: number) => `共 ${total} 行`,
  } : { pageSize: compactSales ? 8 : 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (total: number) => `共 ${total} 行` };
  const exportButton = remote
    ? <Button size="small" icon={<DownloadOutlined />} disabled={(section.total || 0) === 0} href={sectionExportUrl(dashboardPage, section.key, filters, query)}>导出全部 CSV</Button>
    : <Button size="small" icon={<DownloadOutlined />} disabled={!section.rows.length} onClick={() => exportSection(section)}>导出 CSV</Button>;
  const tableSummary = section.summary ? () => <Table.Summary.Row className="dashboard-summary-row">
    {section.columns.map((column, index) => <Table.Summary.Cell key={column.key} index={index}>
      <strong>{formattedValue(section.summary?.[column.key], column, column.label)}</strong>
    </Table.Summary.Cell>)}
  </Table.Summary.Row> : undefined;
  const changeMatrixSort = (sortBy?: string) => {
    void loadSection({
      ...query,
      page: 1,
      sortBy: sortBy || undefined,
      sortOrder: sortBy ? query.sortOrder || 'desc' : undefined,
    });
  };
  const toggleMatrixSortOrder = () => {
    if (!query.sortBy) return;
    void loadSection({
      ...query,
      page: 1,
      sortOrder: query.sortOrder === 'asc' ? 'desc' : 'asc',
    });
  };
  const matrixPagination = matrixKind && remote ? <Pagination
    className="dashboard-matrix-pagination"
    current={query.page}
    pageSize={query.pageSize}
    total={section.total || 0}
    showSizeChanger
    pageSizeOptions={[10, 20, 50, 100, 200]}
    showTotal={total => `共 ${total} 行`}
    onChange={(nextPage, nextPageSize) => void loadSection({
      ...query,
      page: nextPageSize === query.pageSize ? nextPage : 1,
      pageSize: nextPageSize,
    })}
  /> : null;

  return <Card
    className={`dashboard-section dashboard-section-${section.key}`}
    title={section.title}
    extra={<Space wrap className="dashboard-section-actions">
      {matrixKind && remote && <Select
        aria-label={`${section.title}排序字段`}
        size="small"
        showSearch
        value={query.sortBy || ''}
        optionFilterProp="label"
        onChange={value => changeMatrixSort(value || undefined)}
        options={[
          { value: '', label: '默认排序' },
          ...section.columns
            .filter(column => column.sortable !== false)
            .map(column => ({ value: column.key, label: displayLabel(column.label, column) })),
        ]}
        style={{ width: 180 }}
      />}
      {matrixKind && remote && <Button
        size="small"
        aria-label={`${section.title}排序方向`}
        disabled={!query.sortBy}
        onClick={toggleMatrixSortOrder}
      >
        {query.sortOrder === 'asc' ? '升序' : '降序'}
      </Button>}
      {remote && <Input.Search allowClear value={searchDraft} loading={loading} placeholder="搜索当前表格" onChange={event => setSearchDraft(event.target.value)} onSearch={value => void loadSection({ ...query, page: 1, search: value.trim() })} style={{ width: 220 }} />}
      {exportButton}
    </Space>}
  >
    {error && <Alert className="section-load-error" type="error" showIcon message="表格加载失败" description={error} action={<Button size="small" onClick={() => void loadSection(query)}>重试</Button>} />}
    {performance ? <PerformanceOverviewImage section={section} /> : <>
      {matrixKind
        ? loading
          ? <div className="dashboard-matrix-loading"><Skeleton active paragraph={{ rows: 5 }} title={false} /></div>
          : !section.rows.length
            ? <Typography.Text type="secondary">暂无数据</Typography.Text>
            : <>
              <DashboardDecisionMatrix kind={matrixKind} section={section} />
              {matrixPagination}
            </>
        : !loading && !section.rows.length ? <Typography.Text type="secondary">暂无数据</Typography.Text> : <>
        <MiniChart section={section} />
        <Table
          rowKey={(row, index) => String(row._rowId || row.id || `${section.page || 1}-${index}-${Object.values(row).slice(0, 2).join('-')}`)}
          size="small" sticky loading={loading} columns={tableColumns} dataSource={section.rows}
          pagination={pagination} onChange={handleTableChange}
          summary={tableSummary}
          scroll={{ x: 'max-content', y: section.key === 'stores' ? undefined : compactSales ? 250 : section.rows.length > 20 ? 520 : undefined }}
        />
      </>}
    </>}
  </Card>;
}

function selectionFromServer(selected: DashboardPayload['selected']) {
  const result: Record<string, string | string[]> = {};
  Object.entries(selected || {}).forEach(([key, value]) => { result[key] = Array.isArray(value) ? value.map(String) : value == null ? '' : String(value); });
  return result;
}

function selectionParams(selection: Record<string, string | string[]>) {
  const params: Record<string, string> = {};
  filterKeys.forEach(key => {
    const value = selection[key];
    if (Array.isArray(value) && value.length) params[key] = value.join(',');
    else if (typeof value === 'string' && value) params[key] = value;
  });
  return params;
}

function filtersFromUrl() {
  const search = new URLSearchParams(window.location.search); const params: Record<string, string> = {};
  filterKeys.forEach(key => { const value = search.get(key); if (value) params[key] = value; });
  return params;
}

function updateDashboardUrl(page: string, params: Record<string, string>) {
  const url = new URL(window.location.href);
  filterKeys.forEach(key => url.searchParams.delete(key));
  url.searchParams.set('page', page);
  Object.entries(params).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
  window.history.pushState({}, '', url);
  window.dispatchEvent(new Event('sales-dashboard-route-change'));
}

function updatedAtLabel(value: DashboardPayload['updated_at']) {
  if (value === undefined || value === null || value === '') return new Date().toLocaleString('zh-CN', { hour12: false });
  const parsed = typeof value === 'number' ? new Date(value < 10_000_000_000 ? value * 1000 : value) : new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('zh-CN', { hour12: false });
}

function DashboardSkeleton() {
  return <><Card className="filter-card"><Skeleton active paragraph={{ rows: 1 }} title={false} /></Card><div className="metric-grid">{Array.from({ length: 4 }, (_, index) => <Card key={index}><Skeleton active paragraph={{ rows: 1 }} /></Card>)}</div><Card className="dashboard-section"><Skeleton active paragraph={{ rows: 8 }} /></Card></>;
}

export default function DashboardPage({ page, active = true, routeVersion = 0, refreshVersion = 0 }: { page: string; active?: boolean; routeVersion?: number; refreshVersion?: number }) {
  const [data, setData] = useState<DashboardPayload>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selection, setSelection] = useState<Record<string, string | string[]>>({});
  const [appliedParams, setAppliedParams] = useState<Record<string, string>>({});
  const [searchTerms, setSearchTerms] = useState<Record<string, string>>({});
  const [lastUpdated, setLastUpdated] = useState('');
  const [productTab, setProductTab] = useState<ProductManagementTab>(() => productManagementTabFromSearch(window.location.search));
  const [departmentTab, setDepartmentTab] = useState<DepartmentMonitoringTab>(() => departmentMonitoringTabFromSearch(window.location.search));
  const abortRef = useRef<AbortController | undefined>(undefined);
  const requestRef = useRef(0);
  const seenRefreshVersion = useRef(refreshVersion);
  const seenRouteVersion = useRef(routeVersion);

  const load = useCallback(async (params: Record<string, string>) => {
    abortRef.current?.abort();
    const controller = new AbortController(); abortRef.current = controller;
    const requestId = ++requestRef.current;
    setLoading(true); setError(''); setData(undefined);
    try {
      const result = await api.dashboard(page, params, controller.signal);
      if (requestId !== requestRef.current) return;
      const appliedSelection = selectionFromServer(result.selected);
      setData(result); setSelection(appliedSelection); setAppliedParams(selectionParams(appliedSelection));
      setLastUpdated(updatedAtLabel(result.updated_at));
    } catch (loadError) {
      if (controller.signal.aborted) return;
      if (requestId === requestRef.current) setError(loadError instanceof Error ? loadError.message : '看板加载失败');
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [page]);

  useEffect(() => { void load(filtersFromUrl()); return () => abortRef.current?.abort(); }, [load]);
  useEffect(() => {
    if (!active || seenRefreshVersion.current === refreshVersion) return;
    seenRefreshVersion.current = refreshVersion;
    void load(appliedParams);
  }, [active, appliedParams, load, refreshVersion]);
  useEffect(() => {
    if (!active || seenRouteVersion.current === routeVersion) return;
    seenRouteVersion.current = routeVersion;
    if (page === 'products') setProductTab(productManagementTabFromSearch(window.location.search));
    if (page === 'department') setDepartmentTab(departmentMonitoringTabFromSearch(window.location.search));
    void load(filtersFromUrl());
  }, [active, load, page, routeVersion]);
  useEffect(() => {
    const onPopState = () => {
      const urlPage = new URLSearchParams(window.location.search).get('page') || 'overview';
      if (active && urlPage === page) {
        if (page === 'products') setProductTab(productManagementTabFromSearch(window.location.search));
        if (page === 'department') setDepartmentTab(departmentMonitoringTabFromSearch(window.location.search));
        void load(filtersFromUrl());
      }
    };
    window.addEventListener('popstate', onPopState); return () => window.removeEventListener('popstate', onPopState);
  }, [active, load, page]);

  const applyFilters = () => { const params = selectionParams(selection); updateDashboardUrl(page, params); void load(params); };
  const changeProductTab = (value: string) => {
    const next = value === 'low-margin' ? 'low-margin' : 'detail';
    if (next === productTab) return;
    const url = new URL(window.location.href);
    url.searchParams.set('page', 'products');
    url.searchParams.set('tab', next);
    window.history.pushState({}, '', url);
    window.dispatchEvent(new Event('sales-dashboard-route-change'));
    setProductTab(next);
  };
  const changeDepartmentTab = (value: string) => {
    const next = value === 'commission' ? 'commission' : 'performance';
    if (next === departmentTab) return;
    const url = new URL(window.location.href);
    url.searchParams.set('page', 'department');
    url.searchParams.set('tab', next);
    window.history.pushState({}, '', url);
    window.dispatchEvent(new Event('sales-dashboard-route-change'));
    setDepartmentTab(next);
  };
  const matchedOptions = (key: string, options: string[]) => { const keyword = (searchTerms[key] || '').trim().toLocaleLowerCase(); return keyword ? options.filter(value => value.toLocaleLowerCase().includes(keyword)) : options; };
  const selectMatchedOptions = (key: string, options: string[]) => setSelection(current => ({ ...current, [key]: Array.from(new Set([...(Array.isArray(current[key]) ? current[key] : []), ...matchedOptions(key, options)])) }));
  const multiFilter = (key: string, options: string[] | undefined, placeholder: string, width: number) => options ? <Select
    allowClear mode="multiple" showSearch maxTagCount="responsive" value={(selection[key] as string[]) || []}
    onChange={value => setSelection(current => ({ ...current, [key]: value }))}
    onSearch={value => setSearchTerms(current => ({ ...current, [key]: value }))}
    placeholder={placeholder} options={options.map(value => ({ value, label: value }))}
    dropdownRender={menu => <><Button block type="text" disabled={!matchedOptions(key, options).length} onMouseDown={event => event.preventDefault()} onClick={() => selectMatchedOptions(key, options)}>全选当前搜索结果（{matchedOptions(key, options).length}）</Button>{menu}</>}
    style={{ minWidth: width }}
  /> : null;
  const showDepartmentFilters = page !== 'department' || departmentTab === 'commission';
  const filterControls = data && showDepartmentFilters ? <Space wrap>
    {multiFilter('developers', data.filters.developers, '选择开发员', 260)}
    {data.filters.months && (page === 'overview' ? multiFilter('months', data.filters.months, '选择月份', 210) : <Select allowClear value={selection.month as string || undefined} onChange={value => setSelection(current => ({ ...current, month: value || '' }))} placeholder="选择月份" options={data.filters.months.map(value => ({ value, label: value }))} style={{ minWidth: 150 }} />)}
    {multiFilter('departments', data.filters.departments, '选择部门', 200)}
    {multiFilter('store_types', data.filters.store_types, '选择店铺类型', 180)}
    {data.filters.thresholds && <Select allowClear value={selection.threshold as string || undefined} onChange={value => setSelection(current => ({ ...current, threshold: value || '' }))} placeholder="选择库龄" options={data.filters.thresholds.map(value => ({ value, label: value }))} style={{ minWidth: 150 }} />}
    <Button type="primary" loading={loading} icon={<FilterOutlined />} onClick={applyFilters}>应用筛选</Button>
  </Space> : null;
  const compactSales = page === 'sales';
  const sectionCards = data?.sections.map(section => (
    <DashboardSectionCard
      key={section.key}
      initialSection={section}
      dashboardPage={page}
      filters={appliedParams}
      compactSales={compactSales}
    />
  ));
  const visibleSections = page === 'products'
    ? data?.sections.map((section, index) => (
      <div
        className="product-management-tab-pane"
        hidden={section.key !== productTab}
        aria-hidden={section.key !== productTab}
        key={section.key}
      >
        {sectionCards?.[index]}
      </div>
    ))
    : page === 'department'
      ? data?.sections.map((section, index) => {
        const visible = departmentTab === 'commission' ? section.key === 'commission' : section.key !== 'commission';
        return <div
          className="department-monitoring-tab-pane"
          hidden={!visible}
          aria-hidden={!visible}
          key={section.key}
        >
          {sectionCards?.[index]}
        </div>;
      })
    : sectionCards;

  return <div className={`dashboard-page dashboard-page-${page}`}>
    {page === 'products' && <Tabs
      className="product-management-tabs"
      activeKey={productTab}
      onChange={changeProductTab}
      items={[
        { key: 'detail', label: '产品管理明细' },
        { key: 'low-margin', label: '低毛利率 SKU' },
      ]}
    />}
    {page === 'department' && <Tabs
      className="department-monitoring-tabs"
      activeKey={departmentTab}
      onChange={changeDepartmentTab}
      items={[
        { key: 'performance', label: '业绩监控' },
        { key: 'commission', label: '提成监控' },
      ]}
    />}
    <div className="page-heading"><div><Typography.Title level={2}>{data?.title || '数据看板'}</Typography.Title><Typography.Text type="secondary">{pageDescriptions[page]}{lastUpdated && ` · 数据更新时间 ${lastUpdated}`}</Typography.Text></div><Button loading={loading} icon={<ReloadOutlined />} onClick={() => void load(appliedParams)}>刷新</Button></div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="看板加载失败" description={error} action={<Button size="small" onClick={() => void load(filtersFromUrl())}>重试</Button>} />}
    {loading ? <DashboardSkeleton /> : data ? <>
      {filterControls && <Card className="filter-card">{filterControls}</Card>}
      {data.warnings?.length && (page !== 'department' || departmentTab === 'performance') ? <Alert className="dashboard-warning" type="warning" showIcon message="数据质量提醒" description={<ul>{data.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>} /> : null}
      {!data.has_data && <Alert type="info" showIcon message={data.message || '当前没有可展示的数据'} />}
      {data.metrics?.length ? <div className="metric-grid">{data.metrics.map(item => <Card key={item.name}><Statistic title={displayLabel(item.name, item)} value={formattedValue(item.value, item, item.name)} /></Card>)}</div> : null}
      <div className={compactSales ? 'sales-sections' : undefined}>{visibleSections}</div>
    </> : null}
  </div>;
}
