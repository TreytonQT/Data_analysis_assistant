import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Collapse, Image, Input, Space, Statistic, Table, Tag, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import type { DashboardRow, DashboardSection, NewProductCopyLists, NewProductDashboardPayload } from './api';
import { api } from './api';
import { copyWithFeedback, downloadWithFeedback } from './feedback';
import FilterActions from './FilterActions';
import ConfirmFilterSelect from './ConfirmFilterSelect';

type LaunchStage = 'all' | '0-6' | '7-29' | '30-59' | '60-100';
type MonitorStatus = 'all' | 'raise' | 'lower' | 'normal' | 'out_of_stock' | 'observing' | 'invalid';

const STATUS_OPTIONS: Array<{ value: MonitorStatus; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'raise', label: '建议涨价' },
  { value: 'lower', label: '建议降价' },
  { value: 'out_of_stock', label: '已断货' },
  { value: 'observing', label: '新品观察中' },
  { value: 'normal', label: '正常' },
  { value: 'invalid', label: '数据异常' },
];
const STAGE_OPTIONS: Array<{ value: LaunchStage; label: string }> = [
  { value: 'all', label: '全部开售阶段' },
  { value: '0-6', label: '0～6 天' },
  { value: '7-29', label: '7～29 天' },
  { value: '30-59', label: '30～59 天' },
  { value: '60-100', label: '60～100 天' },
];
const SHANGHAI_DATE = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' });

function statusTag(status: unknown) {
  const value = String(status || '');
  const color = value === '建议涨价' ? 'red'
    : value === '建议降价' ? 'orange'
      : value === '已断货' ? 'volcano'
        : value === '数据异常' ? 'default'
          : value === '正常' ? 'green' : 'blue';
  return <Tag color={color}>{value || '—'}</Tag>;
}

function numberText(value: unknown, precision = 2) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: precision }) : String(value);
}

function uploadedAtLabel(value?: string | null) {
  if (!value) return '未知';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString('zh-CN');
}

function rowImage(row: DashboardRow) {
  const image = row.image;
  if (!image || typeof image !== 'object' || !('url' in image)) return <Typography.Text type="secondary">—</Typography.Text>;
  return <Image width={36} height={36} src={image.url} alt={String(row.SKU || 'SKU 图片')} style={{ objectFit: 'cover', borderRadius: 6 }} />;
}

function extraDetails(row: DashboardRow) {
  const countries = ['德国', '法国', '西班牙', '意大利'];
  return <div className="new-product-extra">
    <div className="new-product-extra-row"><strong>近三日销量</strong><span>昨天 {numberText(row['昨天销量'], 0)}</span><span>前天 {numberText(row['前天销量'], 0)}</span><span>上前天 {numberText(row['上前销量'], 0)}</span></div>
    <div className="new-product-extra-row"><strong>站点销量 / 毛利</strong>{countries.map(country =>
      <span key={country}>{country} {numberText(row[country + '销量'], 0)} 件 · {row[country + '毛利率'] == null ? '毛利 —' : '毛利 ' + (Number(row[country + '毛利率']) * 100).toFixed(1) + '%'}
      </span>)}</div>
    <div className="new-product-extra-row"><strong>Rating</strong><span>{String(row.Rating || '暂无 Rating 数据')}</span></div>
  </div>;
}

export default function NewProductMonitorPage({
  active = true,
  routeVersion = 0,
  refreshVersion = 0,
}: {
  active?: boolean;
  routeVersion?: number;
  refreshVersion?: number;
}) {
  const [data, setData] = useState<NewProductDashboardPayload>();
  const [section, setSection] = useState<DashboardSection>();
  const [copyLists, setCopyLists] = useState<NewProductCopyLists>({ raise_skus: [], lower_skus: [], calculation_date: '' });
  const [appliedDevelopers, setAppliedDevelopers] = useState<string[]>([]);
  const [appliedLaunchStage, setAppliedLaunchStage] = useState<LaunchStage>('all');
  const [appliedStatus, setAppliedStatus] = useState<MonitorStatus>('all');
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortBy, setSortBy] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestAbort = useRef<AbortController | undefined>(undefined);
  const requestSequence = useRef(0);

  const baseParams = useMemo(() => {
    const params: Record<string, string> = { launch_stage: appliedLaunchStage };
    if (appliedDevelopers.length) params.developers = appliedDevelopers.join(',');
    if (search) params.search = search;
    return params;
  }, [appliedDevelopers, appliedLaunchStage, search]);

  const loadView = useCallback(async () => {
    requestAbort.current?.abort();
    const controller = new AbortController();
    requestAbort.current = controller;
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError('');
    const params: Record<string, string> = {
      ...baseParams,
      status: appliedStatus,
      page: String(page),
      page_size: String(pageSize),
    };
    if (sortBy) {
      params.sort_by = sortBy;
      params.sort_order = sortOrder;
    }
    try {
      const result = await api.newProductView(params, controller.signal);
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setData(result);
      setSection(result.sections.find(item => item.key === 'detail'));
      setCopyLists(result.copy_lists);
    } catch (reason) {
      if (!controller.signal.aborted && requestId === requestSequence.current) {
        setError(reason instanceof Error ? reason.message : '新品监控加载失败');
      }
    } finally {
      if (!controller.signal.aborted && requestId === requestSequence.current) setLoading(false);
    }
  }, [appliedStatus, baseParams, page, pageSize, sortBy, sortOrder]);

  useEffect(() => {
    if (!active) return;
    void loadView();
    return () => {
      requestAbort.current?.abort();
      requestSequence.current += 1;
    };
  }, [active, loadView, routeVersion, refreshVersion]);

  const refresh = () => { void loadView(); };

  useEffect(() => {
    if (!active || !data?.calculation_date) return;
    const timer = window.setInterval(() => {
      if (SHANGHAI_DATE.format(new Date()) !== data.calculation_date) void loadView();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [active, data?.calculation_date, loadView]);

  const applySearch = (value: string) => {
    setSearchDraft(value);
    const nextSearch = value.trim();
    if (nextSearch === search) return;
    setSearch(nextSearch);
    setPage(1);
  };
  const resetFilters = () => {
    setAppliedDevelopers([]);
    setAppliedLaunchStage('all');
    setAppliedStatus('all');
    setSearchDraft('');
    setSearch('');
    setPage(1);
    setSortBy('');
    setSortOrder('asc');
  };
  const developerOptions = data?.filters.developers || [];

  const copy = (skus: string[], label: string) => copyWithFeedback(skus.join('\n'), label, skus.length);
  const exportUrl = useMemo(() => {
    const params = new URLSearchParams({ ...baseParams, status: appliedStatus });
    if (sortBy) {
      params.set('sort_by', sortBy);
      params.set('sort_order', sortOrder);
    }
    return '/api/dashboard/new-products/sections/detail/export.csv?' + params.toString();
  }, [appliedStatus, baseParams, sortBy, sortOrder]);

  const columns = useMemo(() => [
    { title: '图片', key: 'image', width: 64, render: (_: unknown, row: DashboardRow) => rowImage(row) },
    { title: 'SKU', dataIndex: 'SKU', key: 'SKU', sorter: true, sortOrder: sortBy === 'SKU' ? (sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null, width: 160 },
    { title: 'ASIN', dataIndex: 'ASIN', key: 'ASIN', width: 120 },
    { title: '开发员', dataIndex: '开发员', key: '开发员', width: 110 },
    { title: '开售日期', dataIndex: '开售时间', key: '开售时间', width: 120 },
    { title: '开售天数', dataIndex: '开售天数', key: '开售天数', sorter: true, sortOrder: sortBy === '开售天数' ? (sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null, width: 100 },
    { title: '可售', dataIndex: '可售数量', key: '可售数量', sorter: true, sortOrder: sortBy === '可售数量' ? (sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null, width: 90, render: (value: unknown) => numberText(value, 0) },
    { title: '日均销量', dataIndex: '日均销量', key: '日均销量', sorter: true, sortOrder: sortBy === '日均销量' ? (sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null, width: 105, render: (value: unknown) => numberText(value) },
    { title: '覆盖天数', dataIndex: '可售覆盖天数', key: '可售覆盖天数', sorter: true, sortOrder: sortBy === '可售覆盖天数' ? (sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null, width: 105, render: (value: unknown, row: DashboardRow) => row['日均销量'] !== null && row['日均销量'] !== undefined && Number(row['日均销量']) === 0 && Number(row['可售数量']) > 0 ? '∞' : numberText(value) },
    { title: '昨日', dataIndex: '昨天销量', key: '昨天销量', width: 78, render: (value: unknown) => numberText(value, 0) },
    { title: '7天', dataIndex: '7天销量', key: '7天销量', width: 78, render: (value: unknown) => numberText(value, 0) },
    { title: '14天', dataIndex: '14天销量', key: '14天销量', width: 78, render: (value: unknown) => numberText(value, 0) },
    { title: '30天', dataIndex: '30天销量', key: '30天销量', width: 78, render: (value: unknown) => numberText(value, 0) },
    { title: '90天', dataIndex: '90天销量', key: '90天销量', width: 78, render: (value: unknown) => numberText(value, 0) },
    { title: '提醒状态', dataIndex: '监控状态', key: '监控状态', width: 150, render: (value: unknown) => statusTag(value) },
    { title: '提醒原因', dataIndex: '提醒原因', key: '提醒原因', width: 190 },
  ], [sortBy, sortOrder]);

  const metrics = data?.metrics || [];
  const metricsByName = new Map(metrics.map(item => [item.name, item]));
  const mainMetricNames = ['新品 SKU 数', '建议涨价', '建议降价', '可售数量合计', '近30天销量'];
  const extraMetricNames = ['已断货', '新品观察中', '数据异常'];
  const pagination = {
    current: page,
    pageSize,
    total: section?.total || 0,
    showSizeChanger: true,
    pageSizeOptions: [20, 50, 100, 200],
    showTotal: (total: number) => '共 ' + total + ' 个 SKU',
    onChange: (nextPage: number, nextPageSize: number) => {
      setPage(nextPage);
      if (nextPageSize !== pageSize) setPageSize(nextPageSize);
    },
  };

  return <div className="dashboard-page dashboard-page-new-products">
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>新品监控</Typography.Title>
        <Typography.Text type="secondary">
          首批到货后 100 天内 · 计算日期 {data?.calculation_date || '—'} · 运营表上传于 {uploadedAtLabel(data?.source_uploaded_at)}
        </Typography.Text>
      </div>
      <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>刷新</Button>
    </div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="新品监控加载失败" description={error} action={<Button size="small" onClick={refresh}>重试</Button>} />}
    {data && (data.excluded_invalid_launch_count || 0) > 0 &&
      <Alert className="dashboard-warning" type="warning" showIcon message={'有 ' + data.excluded_invalid_launch_count + ' 个 SKU 缺少或有无效开售日期，未纳入新品监控。'} />}
    <Card className="filter-card">
      <Space wrap>
        <ConfirmFilterSelect
          mode="multiple"
          ariaLabel="开发员"
          value={appliedDevelopers}
          options={developerOptions.map(value => ({ value, label: value }))}
          onConfirm={value => { setAppliedDevelopers(Array.isArray(value) ? value.map(String) : []); setPage(1); }}
          placeholder="全部开发员"
          style={{ minWidth: 240, maxWidth: 400 }}
        />
        <ConfirmFilterSelect
          mode="single"
          ariaLabel="开售阶段"
          value={appliedLaunchStage}
          normalizeValue={value => value || 'all'}
          options={STAGE_OPTIONS}
          onConfirm={value => { setAppliedLaunchStage((value ? String(value) : 'all') as LaunchStage); setPage(1); }}
          placeholder="全部开售阶段"
          style={{ width: 150 }}
        />
        <ConfirmFilterSelect
          mode="single"
          ariaLabel="提醒状态"
          value={appliedStatus}
          normalizeValue={value => value || 'all'}
          options={STATUS_OPTIONS}
          onConfirm={value => { setAppliedStatus((value ? String(value) : 'all') as MonitorStatus); setPage(1); }}
          placeholder="全部状态"
          style={{ width: 160 }}
        />
        <Input.Search
          allowClear
          value={searchDraft}
          placeholder="搜索 SKU 或 ASIN"
          onChange={event => setSearchDraft(event.target.value)}
          onSearch={applySearch}
          style={{ width: 240 }}
        />
        <FilterActions onReset={resetFilters} />
      </Space>
    </Card>
    {data && <div className="metric-grid new-product-metrics">
      {mainMetricNames.map(name => {
        const item = metricsByName.get(name);
        return <Card key={name}><Statistic title={name} value={item?.value == null ? 0 : Number(item.value)} /></Card>;
      })}
    </div>}
    {data && <Space className="new-product-status-counts" wrap>
      {extraMetricNames.map(name => {
        const item = metricsByName.get(name);
        const color = name === '已断货' ? 'volcano' : name === '数据异常' ? 'red' : 'blue';
        return <Badge key={name} color={color} text={name + '：' + numberText(item?.value, 0)} />;
      })}
    </Space>}
    {data && <Typography.Text className="new-product-copy-scope" type="secondary">清单按当前已应用的开发员、开售阶段和SKU/ASIN搜索生成，忽略提醒状态和表格分页。</Typography.Text>}
    {data && <div className="new-product-copy-grid">
      <Card title={'建议涨价 SKU（' + copyLists.raise_skus.length + '）'} extra={<Button type="primary" danger disabled={loading} onClick={() => void copy(copyLists.raise_skus, '涨价 SKU')}>复制涨价 SKU</Button>}>
        <Collapse items={[{ key: 'raise', label: '查看清单（' + copyLists.raise_skus.length + '）', children: <Input.TextArea readOnly value={copyLists.raise_skus.join('\n')} autoSize={{ minRows: 1, maxRows: 5 }} placeholder="暂无建议涨价 SKU" /> }]} />
      </Card>
      <Card title={'建议降价 SKU（' + copyLists.lower_skus.length + '）'} extra={<Button type="primary" disabled={loading} onClick={() => void copy(copyLists.lower_skus, '降价 SKU')}>复制降价 SKU</Button>}>
        <Collapse items={[{ key: 'lower', label: '查看清单（' + copyLists.lower_skus.length + '）', children: <Input.TextArea readOnly value={copyLists.lower_skus.join('\n')} autoSize={{ minRows: 1, maxRows: 5 }} placeholder="暂无建议降价 SKU" /> }]} />
      </Card>
    </div>}
    <Card
      className="dashboard-section new-product-table-card"
      title="新品监控明细"
      extra={<Button icon={<DownloadOutlined />} disabled={loading || !section?.total} onClick={() => void downloadWithFeedback(exportUrl, '新品监控明细.csv', '新品监控明细')}>导出筛选结果</Button>}
    >
      <Table<DashboardRow>
        rowKey={row => String(row.SKU) + '-' + String(row.ASIN)}
        columns={columns}
        dataSource={section?.rows || []}
        loading={loading}
        size="small"
        scroll={{ x: 1750 }}
        pagination={pagination}
        expandable={{ expandedRowRender: extraDetails }}
        onChange={(_pagination, _filters, sorter, extra) => {
          if (extra.action !== 'sort') return;
          const selected = Array.isArray(sorter) ? sorter[0] : sorter;
          setSortBy(selected?.order ? String(selected.columnKey || '') : '');
          setSortOrder(selected?.order === 'descend' ? 'desc' : 'asc');
          setPage(1);
        }}
      />
    </Card>
  </div>;
}
