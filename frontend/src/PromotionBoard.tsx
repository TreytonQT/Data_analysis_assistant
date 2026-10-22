import { useCallback, useEffect, useRef, useState } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { feedbackMessage as message, copyWithFeedback, downloadWithFeedback, writeClipboardText } from './feedback';
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  ReloadOutlined,
  StopOutlined,
  TagsOutlined,
} from '@ant-design/icons';
import type { TableProps } from 'antd';
import { PricingBatches, PricingHistory, PricingRegistration } from './PricingPanels';
import FilterActions from './FilterActions';
import ConfirmFilterSelect from './ConfirmFilterSelect';
import {
  api,
  type PromotionCandidate,
  type PromotionInput,
  type PromotionDiscount,
  type PromotionActivitySummary,
  type PromotionOverview,
  type PromotionPage,
  type LastPromotionRecord,
  type PromotionRecord,
  type PromotionStatus,
  type PromotionStatusFilter,
  type ListingObservation,
} from './api';

type ListQuery = {
  page: number;
  pageSize: number;
  search: string;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  developers: string[];
};

type PromotionFormValues = { promotion_name: string; start_date: Dayjs; end_date?: Dayjs | null };
type PromotionDialog = { kind: 'create'; skus: string[]; discount?: number } | { kind: 'edit'; record: PromotionRecord } | null;
type PromotionDataTab = 'adjustments' | 'history' | 'records' | 'last-promotions' | 'actual-prices' | 'candidates-10' | 'candidates-8' | 'candidates-5';

const defaultQuery: ListQuery = { page: 1, pageSize: 50, search: '', developers: [] };
const statusColours: Record<PromotionStatus, string> = { pending: 'gold', active: 'green', ended: 'default' };
const promotionDataTabs: PromotionDataTab[] = ['adjustments', 'history', 'records', 'last-promotions', 'actual-prices', 'candidates-10', 'candidates-8', 'candidates-5'];

export function promotionDataTabFromSearch(search: string): PromotionDataTab {
  const value = new URLSearchParams(search).get('promotion_view');
  return promotionDataTabs.includes(value as PromotionDataTab) ? value as PromotionDataTab : 'records';
}

export function promotionStatusLabel(status: PromotionStatus) {
  return status === 'active' ? '正在促销' : status === 'pending' ? '待开始' : '已结束';
}

export function promotionRuleLabel(ruleKey: string, discount: number) {
  const labels: Record<string, string> = {
    sales_le_10: '可售≥20，90天销量≤10',
    sales_11_20: '可售≥20，90天销量11–20',
    sales_21_30: '可售≥20，90天销量21–30',
    aged_90d: '90天以上库存兜底',
    manual: '手动添加',
  };
  return labels[ruleKey] || (discount === 10 ? '可售≥20，90天销量≤10' : discount === 8 ? '可售≥20，90天销量≤20' : '建议降价促销');
}

export function parseManualSkus(value: string) {
  return [...new Set(value.split(/\r?\n/).map(item => item.trim()).filter(Boolean))];
}

function discountTagColor(discount: number) {
  return discount === 10 ? 'red' : discount === 8 ? 'orange' : discount === 5 ? 'blue' : 'purple';
}

export function skuCopyText(skus: string[]) {
  return [...new Set(skus.map(value => value.trim()).filter(Boolean))].join('\n');
}

export async function writeClipboard(text: string) {
  return writeClipboardText(text);
}

function formatNumber(value: unknown, maximumFractionDigits = 2) {
  if (value === null || value === undefined || value === '') return '-';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '-';
  return numeric.toLocaleString('zh-CN', { maximumFractionDigits });
}

function formatUpdatedAt(value?: string | number | null) {
  if (!value) return '';
  const parsed = typeof value === 'number' && value < 10_000_000_000 ? dayjs.unix(value) : dayjs(value);
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : '';
}

export function promotionDateRange(startDate: string, endDate?: string | null) {
  return `${startDate} 至 ${endDate || '持续促销'}`;
}

function queryParams(query: ListQuery, includePage = true) {
  const params: Record<string, string | number | undefined> = {
    search: query.search || undefined,
    sort_by: query.sortBy,
    sort_order: query.sortOrder,
    developers: query.developers.length ? query.developers.join(',') : undefined,
  };
  if (includePage) {
    params.page = query.page;
    params.page_size = query.pageSize;
  }
  return params;
}

function exportUrl(path: string, query: ListQuery, extra?: Record<string, string>) {
  const params = new URLSearchParams();
  Object.entries({ ...queryParams(query, false), ...extra }).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value));
  });
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}



function sortableColumn<T>(key: keyof T & string, title: string, query: ListQuery, width?: number) {
  return {
    key,
    dataIndex: key,
    title,
    width,
    sorter: true,
    sortOrder: query.sortBy === key ? (query.sortOrder === 'asc' ? 'ascend' as const : 'descend' as const) : null,
  };
}

function applyTableSort<T>(sorter: Parameters<NonNullable<TableProps<T>['onChange']>>[2], setQuery: React.Dispatch<React.SetStateAction<ListQuery>>) {
  const selected = Array.isArray(sorter) ? sorter[0] : sorter;
  const field = selected?.field || selected?.columnKey;
  setQuery(current => ({
    ...current,
    page: 1,
    sortBy: selected?.order && field ? String(field) : undefined,
    sortOrder: selected?.order === 'ascend' ? 'asc' : selected?.order === 'descend' ? 'desc' : undefined,
  }));
}

function LiftSummaryChart({ rows, deletingName, onDelete }: { rows: PromotionActivitySummary[]; deletingName: string | null; onDelete: (row: PromotionActivitySummary) => void }) {
  const maximum = Math.max(...rows.map(row => Math.abs(Number(row.daily_lift) || 0)), 1);
  return <div className="promotion-lift-chart" role="img" aria-label="各促销活动近7天与近30天日均差对比">
    {rows.map(row => {
      const lift = Number(row.daily_lift) || 0;
      return <div className="promotion-lift-row" key={row.activity_id}>
        <div className="promotion-activity-meta">
          <Space size={6} wrap>
            <Tag color="blue">{row.promotion_name}</Tag>
            {(row.discount_percents || []).map(discount => <Tag key={discount} color={discountTagColor(discount)}>-{discount}%</Tag>)}
            <Tag color={statusColours[row.status]}>{promotionStatusLabel(row.status)}</Tag>
          </Space>
          <Typography.Text type="secondary">{promotionDateRange(row.start_date, row.end_date)}</Typography.Text>
        </div>
        <div className="promotion-lift-track"><i className={lift >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.abs(lift) / maximum * 50}%` }} /></div>
        <strong className={lift < 0 ? 'promotion-negative' : 'promotion-positive'}>{lift > 0 ? '+' : ''}{formatNumber(lift)}</strong>
        <Typography.Text type="secondary">{formatNumber(row.sku_count, 0)} 个 SKU</Typography.Text>
        <Popconfirm
          title={`删除“${row.promotion_name}”促销活动？`}
          description="会删除该活动下的全部 SKU 活动记录，但会保留 SKU 最近登记限时活动记录。删除后的活动不能恢复。"
          onConfirm={() => onDelete(row)}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        ><Button size="small" type="link" danger icon={<DeleteOutlined />} loading={deletingName === row.activity_id} disabled={deletingName !== null}>删除活动</Button></Popconfirm>
      </div>;
    })}
  </div>;
}

function AdjustmentLiftSummaryChart({ rows }: { rows: NonNullable<PromotionOverview['by_adjustment']> }) {
  const maximum = Math.max(...rows.map(row => Math.abs(Number(row.daily_lift) || 0)), 1);
  return <div className="promotion-lift-chart" role="img" aria-label="各长期调价批次近7天与近30天日均差对比">
    {rows.map(row => {
      const lift = Number(row.daily_lift) || 0;
      return <div className="promotion-lift-row" key={row.batch_id}>
        <div className="promotion-activity-meta">
          <Space size={6} wrap>
            <Tag color="blue">{row.name}</Tag>
            <Tag color={discountTagColor(Number(row.discount_percent))}>-{row.discount_percent}%</Tag>
            <Tag color={row.status === 'active' ? 'green' : 'gold'}>{row.status === 'active' ? '已生效' : '待生效'}</Tag>
          </Space>
          <Typography.Text type="secondary">{row.effective_date} 起 · 长期调价</Typography.Text>
        </div>
        <div className="promotion-lift-track"><i className={lift >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.abs(lift) / maximum * 50}%` }} /></div>
        <strong className={lift < 0 ? 'promotion-negative' : 'promotion-positive'}>{lift > 0 ? '+' : ''}{formatNumber(lift)}</strong>
        <Typography.Text type="secondary">{formatNumber(row.sku_count, 0)} 个 SKU</Typography.Text>
        <Typography.Text type="secondary">近7天与近30天日均差</Typography.Text>
      </div>;
    })}
  </div>;
}

function PromotionOverviewPanel({ refreshToken, onRefresh }: { refreshToken: number; onRefresh: () => void }) {
  const [data, setData] = useState<PromotionOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [deletingName, setDeletingName] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.promotionOverview(controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '促销汇总加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshToken, retry]);

  const removeActivity = async (row: PromotionActivitySummary) => {
    const operationKey = `promotion-activity-delete-${row.promotion_name}`;
    setDeletingName(row.activity_id);
    message.loading({ key: operationKey, content: `正在删除“${row.promotion_name}”活动…`, duration: 0 });
    try {
      const result = await api.deletePromotionActivity(row.activity_id);
      message.success({ key: operationKey, content: `已删除“${row.promotion_name}”活动及 ${result.deleted} 条活动记录，SKU 最近登记限时活动记录已保留` });
      onRefresh();
    } catch (reason) {
      message.error({ key: operationKey, content: reason instanceof Error ? reason.message : '删除促销活动失败', duration: 6 });
    } finally {
      setDeletingName(null);
    }
  };

  if (loading && !data) return <Card className="promotion-overview-card"><Skeleton active paragraph={{ rows: 4 }} /></Card>;
  return <>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="促销汇总加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    {data && <>
      <div className="promotion-metric-grid">
        <Card><Statistic title="长期调价 SKU" value={formatNumber(data.adjusted_sku_count, 0)} suffix="个" /></Card>
        <Card><Statistic title="两者同时生效 SKU" value={formatNumber(data.overlap_sku_count, 0)} suffix="个" /></Card>
        <Card><Statistic title="正在限时促销 SKU" value={formatNumber(data.active_sku_count, 0)} suffix="个" /></Card>
        <Card><Statistic title="7天日均销量合计" value={formatNumber(data.average_7d_total)} /></Card>
        <Card><Statistic title="30天日均销量合计" value={formatNumber(data.average_30d_total)} /></Card>
        <Card><Statistic title="近7天与近30天日均差合计" value={`${Number(data.daily_lift_total) > 0 ? '+' : ''}${formatNumber(data.daily_lift_total)}`} valueStyle={{ color: Number(data.daily_lift_total) < 0 ? '#ef4444' : '#16a34a' }} /></Card>
        <Card><Statistic title="单 SKU 平均日均差" value={`${Number(data.daily_lift_average) > 0 ? '+' : ''}${formatNumber(data.daily_lift_average)}`} valueStyle={{ color: Number(data.daily_lift_average) < 0 ? '#ef4444' : '#16a34a' }} /></Card>
      </div>
      {Number(data.source_missing_count) > 0 && <Alert className="promotion-source-warning" type="warning" showIcon message={`${formatNumber(data.source_missing_count, 0)} 个促销 SKU 已不在当前源数据中`} description="记录仍会保留，但不会计入上方销量趋势汇总。" />}
      <Alert type="info" message="总体销量按 SKU 去重；近7天与近30天日均差仅反映趋势，不代表单项措施带来的独立增量。" />
      <Card title="长期调价批次 · 近7天与近30天日均差">
        <AdjustmentLiftSummaryChart rows={data.by_adjustment || []} />
      </Card>
      <Card className="promotion-overview-card" title="限时活动 · 近7天与近30天日均差" extra={formatUpdatedAt(data.updated_at) ? <Typography.Text type="secondary">数据更新时间 {formatUpdatedAt(data.updated_at)}</Typography.Text> : null}>
        <LiftSummaryChart rows={data.by_promotion || []} deletingName={deletingName} onDelete={removeActivity} />
      </Card>
    </>}
  </>;
}

function CandidateTable({ discount, refreshToken, onMark }: { discount: PromotionDiscount; refreshToken: number; onMark: (skus: string[]) => void }) {
  const [data, setData] = useState<PromotionPage<PromotionCandidate> | null>(null);
  const [query, setQuery] = useState<ListQuery>(defaultQuery);
  const [searchDraft, setSearchDraft] = useState('');
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [loading, setLoading] = useState(true);
  const [copyingAll, setCopyingAll] = useState(false);
  const [creatingFiltered, setCreatingFiltered] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.promotionCandidates(discount, queryParams(query) as Parameters<typeof api.promotionCandidates>[1], controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '候选 SKU 加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [discount, query.page, query.pageSize, query.search, query.sortBy, query.sortOrder, query.developers.join(','), refreshToken, retry]);

  useEffect(() => setSelected([]), [refreshToken]);

  const copy = async (skus: string[]) => {
    await copyWithFeedback(skuCopyText(skus), 'SKU', skus.length);
  };
  const copyAll = async () => {
    setCopyingAll(true);
    try {
      const text = await api.promotionCandidateSkus(discount, { search: query.search || undefined, developers: query.developers.length ? query.developers.join(',') : undefined, sort_by: query.sortBy, sort_order: query.sortOrder });
      const count = text.split(/\r?\n/).filter(Boolean).length;
      await copyWithFeedback(text.trim(), 'SKU', count);
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '复制失败，请重试'); }
    finally { setCopyingAll(false); }
  };

  const createFiltered = async () => {
    if (creatingFiltered) return;
    setCreatingFiltered(true);
    try {
      const text = await api.promotionCandidateSkus(discount, {
        search: query.search || undefined,
        developers: query.developers.length ? query.developers.join(',') : undefined,
        sort_by: query.sortBy,
        sort_order: query.sortOrder,
      });
      const skus = [...new Set(text.split(/\r?\n/).map(value => value.trim()).filter(Boolean))];
      if (!skus.length) {
        message.info('当前筛选没有可创建的 SKU');
        return;
      }
      if (skus.length > 5000) {
        message.error('筛选结果超过 5000 个 SKU，请缩小筛选范围');
        return;
      }
      onMark(skus);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '筛选结果加载失败，请重试');
    } finally {
      setCreatingFiltered(false);
    }
  };

  const columns: NonNullable<TableProps<PromotionCandidate>['columns']> = [
    { ...sortableColumn<PromotionCandidate>('sku', 'SKU', query, 170), fixed: 'left', render: value => <Typography.Text copyable={{ text: String(value), onCopy: () => message.success({ key: `copy-sku-${String(value)}`, content: `SKU ${String(value)}已复制` }) }}>{String(value)}</Typography.Text> },
    { ...sortableColumn<PromotionCandidate>('asin', 'ASIN', query, 130), render: value => value || '-' },
    { ...sortableColumn<PromotionCandidate>('developer', '开发员', query, 110), render: value => value || '未配置' },
    { ...sortableColumn<PromotionCandidate>('available_inventory', '可售库存', query, 110), align: 'right', render: value => formatNumber(value, 0) },
    { ...sortableColumn<PromotionCandidate>('sales_90d', '90天销量', query, 110), align: 'right', render: value => formatNumber(value, 2) },
    { ...sortableColumn<PromotionCandidate>('aged_inventory_90d', '90天以上库存', query, 130), align: 'right', render: value => formatNumber(value, 0) },
    { ...sortableColumn<PromotionCandidate>('average_7d', '7天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionCandidate>('average_30d', '30天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionCandidate>('daily_lift', '近7天与近30天日均差', query, 110), align: 'right', render: value => <span className={Number(value) < 0 ? 'promotion-negative' : 'promotion-positive'}>{Number(value) > 0 ? '+' : ''}{formatNumber(value)}</span> },
    { key: 'discount_percent', dataIndex: 'discount_percent', title: '建议折扣', width: 100, render: value => <Tag color={discountTagColor(discount)}>-{value}%</Tag> },
    { key: 'rule_key', dataIndex: 'rule_key', title: '命中策略', width: 210, render: value => promotionRuleLabel(String(value), discount) },
    { key: 'action', title: '操作', fixed: 'right', width: 110, render: (_, row) => <Button size="small" type="link" icon={<TagsOutlined />} onClick={() => onMark([row.sku])}>标记促销</Button> },
  ];

  const applySearch = (value: string) => {
    setSearchDraft(value);
    const nextSearch = value.trim();
    if (nextSearch === query.search) return;
    setSelected([]);
    setQuery(current => ({ ...current, page: 1, search: nextSearch }));
  };
  const resetFilters = () => {
    setSearchDraft('');
    setSelected([]);
    setQuery({ ...defaultQuery });
  };
  const developerOptions = data?.developers || [];
  return <Card className="promotion-table-card">
    <div className="promotion-table-toolbar">
      <Space wrap>
        <Input.Search value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={applySearch} allowClear placeholder="搜索 SKU、ASIN、开发员" style={{ width: 260 }} />
        <ConfirmFilterSelect mode="multiple" ariaLabel="开发员" value={query.developers} onConfirm={value => { setSelected([]); setQuery(current => ({ ...current, page: 1, developers: Array.isArray(value) ? value.map(String) : [] })); }} placeholder="全部开发员" options={developerOptions.map(value => ({ value, label: value }))} style={{ minWidth: 220 }} />
        <FilterActions onReset={resetFilters} />
      </Space>
      <Space wrap>
        <Button icon={<CopyOutlined />} disabled={!selected.length || loading} onClick={() => void copy(selected.map(String))}>复制所选（{selected.length}）</Button>
        <Button icon={<CopyOutlined />} loading={copyingAll} disabled={loading} onClick={() => void copyAll()}>复制全部匹配</Button>
        <Button icon={<DownloadOutlined />} disabled={loading} onClick={() => void downloadWithFeedback(exportUrl(`/api/promotions/candidates/${discount}/export.csv`, query), "促销候选.csv", `促销候选 -${discount}%`)}>导出筛选结果</Button>
        <Button
          type="primary"
          icon={<TagsOutlined />}
          loading={creatingFiltered}
          disabled={!data || data.total === 0 || loading || copyingAll || creatingFiltered}
          onClick={() => void createFiltered()}
        >筛选结果创建促销（{data?.total || 0}）</Button>
        <Button type="primary" icon={<TagsOutlined />} disabled={!selected.length || loading} onClick={() => onMark(selected.map(String))}>批量标记促销</Button>
      </Space>
    </div>
    {error && <Alert className="section-load-error" type="error" showIcon message="候选表加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    <Table<PromotionCandidate>
      rowKey="sku"
      size="small"
      loading={loading}
      dataSource={data?.rows || []}
      columns={columns}
      scroll={{ x: 1550 }}
      rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: setSelected }}
      pagination={{ current: query.page, pageSize: query.pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 条` }}
      onChange={(pagination, _filters, sorter, extra) => {
        if (extra.action === 'sort') applyTableSort(sorter, setQuery);
        else setQuery(current => ({ ...current, page: pagination.pageSize !== current.pageSize ? 1 : pagination.current || 1, pageSize: pagination.pageSize || 50 }));
      }}
    />
  </Card>;
}

function LastPromotionTable({ refreshToken }: { refreshToken: number }) {
  const [data, setData] = useState<PromotionPage<LastPromotionRecord> | null>(null);
  const [query, setQuery] = useState<ListQuery>(defaultQuery);
  const [searchDraft, setSearchDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.lastPromotions(queryParams(query) as Parameters<typeof api.lastPromotions>[0], controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '最后一次促销记录加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query.page, query.pageSize, query.search, query.sortBy, query.sortOrder, refreshToken, retry]);

  const applySearch = (value = searchDraft) => {
    setSearchDraft(value);
    setQuery(current => ({ ...current, page: 1, search: value.trim() }));
  };
  const resetSearch = () => {
    setSearchDraft('');
    setQuery({ ...defaultQuery });
  };
  const columns: NonNullable<TableProps<LastPromotionRecord>['columns']> = [
    { ...sortableColumn<LastPromotionRecord>('sku', 'SKU', query, 220), fixed: 'left', render: value => <Typography.Text copyable={{ text: String(value), onCopy: () => message.success({ key: `copy-sku-${String(value)}`, content: `SKU ${String(value)}已复制` }) }}>{String(value)}</Typography.Text> },
    { ...sortableColumn<LastPromotionRecord>('promotion_content', '促销内容', query, 460), render: value => String(value || '-') },
  ];

  return <Card className="promotion-table-card promotion-last-promotion-card">
    <div className="promotion-table-toolbar">
      <Space wrap>
        <Input.Search value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={applySearch} allowClear placeholder="搜索 SKU 或促销内容" style={{ width: 320 }} />
        <FilterActions onReset={resetSearch} />
        <Button icon={<DownloadOutlined />} disabled={loading} onClick={() => void downloadWithFeedback(exportUrl('/api/promotions/last-promotions/export.csv', query), 'last-promotions.csv', 'SKU最近登记限时活动')}>导出筛选结果</Button>
      </Space>
    </div>
    {error && <Alert className="section-load-error" type="error" showIcon message="最后一次促销记录加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    <Table<LastPromotionRecord>
      rowKey="sku"
      size="small"
      loading={loading}
      dataSource={data?.rows || []}
      columns={columns}
      scroll={{ x: 700 }}
      pagination={{ current: query.page, pageSize: query.pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 条` }}
      onChange={(pagination, _filters, sorter, extra) => {
        if (extra.action === 'sort') applyTableSort(sorter, setQuery);
        else setQuery(current => ({ ...current, page: pagination.pageSize !== current.pageSize ? 1 : pagination.current || 1, pageSize: pagination.pageSize || 50 }));
      }}
    />
  </Card>;
}

function PromotionDateModal({ dialog, onClose, onSaved }: { dialog: PromotionDialog; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<PromotionFormValues>();
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!dialog) return;
    form.resetFields();
    form.setFieldsValue(dialog.kind === 'edit' ? {
      promotion_name: dialog.record.promotion_name,
      start_date: dayjs(dialog.record.start_date), end_date: dialog.record.end_date ? dayjs(dialog.record.end_date) : null,
    } : { promotion_name: '', start_date: dayjs(), end_date: null });
  }, [dialog, form]);

  const close = () => { if (!savingRef.current) { form.resetFields(); onClose(); } };
  const submit = async () => {
    if (!dialog || savingRef.current) return;
    savingRef.current = true;
    let values: PromotionFormValues;
    try { values = await form.validateFields(); }
    catch { savingRef.current = false; return; }
    setSaving(true);
    const payload: PromotionInput = {
      promotion_name: values.promotion_name,
      start_date: values.start_date.format('YYYY-MM-DD'),
      end_date: values.end_date ? values.end_date.format('YYYY-MM-DD') : null,
    };
    const operationKey = dialog.kind === 'edit' ? `promotion-edit-${dialog.record.id}` : 'promotion-create';
    message.loading({ key: operationKey, content: dialog.kind === 'edit' ? `正在更新促销 ${dialog.record.sku}…` : `正在标记 ${dialog.skus.length} 个促销 SKU…`, duration: 0 });
    try {
      if (dialog.kind === 'edit') await api.updatePromotion(dialog.record.id, payload);
      else await api.createPromotions(dialog.skus, payload);
      message.success({ key: operationKey, content: dialog.kind === 'edit' ? '促销日期已更新' : `已标记 ${dialog.skus.length} 个促销 SKU` });
      form.resetFields(); onClose(); onSaved();
    } catch (reason) { message.error({ key: operationKey, content: reason instanceof Error ? reason.message : '保存失败，请重试', duration: 6 }); }
    finally { savingRef.current = false; setSaving(false); }
  };

  const skus = dialog?.kind === 'create' ? dialog.skus : [];
  return <Modal
    title={dialog?.kind === 'edit' ? `编辑促销 · ${dialog.record.sku}` : '标记正在促销'}
    open={Boolean(dialog)}
    onCancel={close}
    onOk={() => void submit()}
    okText="保存"
    cancelText="取消"
    confirmLoading={saving}
    closable={!saving}
    maskClosable={!saving}
    keyboard={!saving}
    cancelButtonProps={{ disabled: saving }}
    destroyOnHidden
  >
    {dialog?.kind === 'create' && <Alert className="promotion-dialog-summary" type="info" showIcon message={`将标记 ${skus.length} 个 SKU`} description={<Typography.Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }} copyable={{ text: skuCopyText(skus), onCopy: () => message.success({ key: 'copy-promotion-skus', content: `已复制 ${skus.length} 个 SKU` }) }}>{skus.join('、')}</Typography.Paragraph>} />}
    <Form form={form} layout="vertical" preserve={false}>
      <Form.Item name="promotion_name" label="促销名称" rules={[
        { required: true, whitespace: true, message: '请输入促销名称' },
        { max: 100, message: '促销名称不能超过 100 个字符' },
      ]}><Input maxLength={100} showCount placeholder="例如：8月会员日促销" /></Form.Item>
      <Form.Item name="start_date" label="开始日期" rules={[{ required: true, message: '请选择开始日期' }]}><DatePicker allowClear={false} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="end_date" label="结束日期" dependencies={['start_date']} rules={[{ required: true, message: '请选择结束日期' }, ({ getFieldValue }) => ({ validator(_, value?: Dayjs | null) { const start = getFieldValue('start_date') as Dayjs | undefined; return value && start && value.isBefore(start, 'day') ? Promise.reject(new Error('结束日期不能早于开始日期')) : Promise.resolve(); } })]}><DatePicker placeholder="请选择结束日期" style={{ width: '100%' }} /></Form.Item>
      <Typography.Text type="secondary">结束日期当天仍计为“正在促销”，次日自动转为“已结束”。</Typography.Text>
    </Form>
  </Modal>;
}

function RecordsTable({ refreshToken, onRefresh, onEdit, onManualAdd }: { refreshToken: number; onRefresh: () => void; onEdit: (record: PromotionRecord) => void; onManualAdd: () => void }) {
  const [data, setData] = useState<PromotionPage<PromotionRecord> | null>(null);
  const [query, setQuery] = useState<ListQuery>(defaultQuery);
  const [status, setStatus] = useState<PromotionStatusFilter>('active');
  const [searchDraft, setSearchDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.promotionRecords({ ...queryParams(query), status } as Parameters<typeof api.promotionRecords>[0], controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '促销记录加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [status, query.page, query.pageSize, query.search, query.sortBy, query.sortOrder, query.developers.join(','), refreshToken, retry]);

  const applySearch = (value: string) => {
    setSearchDraft(value);
    const nextSearch = value.trim();
    if (nextSearch === query.search) return;
    setQuery(current => ({ ...current, page: 1, search: nextSearch }));
  };
  const resetFilters = () => {
    setStatus('active');
    setSearchDraft('');
    setQuery({ ...defaultQuery });
  };
  const developerOptions = data?.developers || [];

  const endToday = async (record: PromotionRecord) => {
    const operationKey = `promotion-end-${record.id}`;
    setActionId(record.id);
    message.loading({ key: operationKey, content: `正在结束 ${record.sku} 的促销…`, duration: 0 });
    try {
      await api.updatePromotion(record.id, {
        promotion_name: record.promotion_name,
        start_date: record.start_date,
        end_date: dayjs().format('YYYY-MM-DD'),
      });
      message.success({ key: operationKey, content: `${record.sku}结束日期已设为今天` }); onRefresh();
    } catch (reason) { message.error({ key: operationKey, content: reason instanceof Error ? reason.message : `${record.sku}结束促销失败`, duration: 6 }); }
    finally { setActionId(null); }
  };
  const remove = async (record: PromotionRecord) => {
    const operationKey = `promotion-delete-${record.id}`;
    setActionId(record.id);
    message.loading({ key: operationKey, content: `正在删除 ${record.sku} 的促销记录…`, duration: 0 });
    try { await api.deletePromotion(record.id); message.success({ key: operationKey, content: `${record.sku}促销记录已删除，SKU 最近登记限时活动记录已保留` }); onRefresh(); }
    catch (reason) { message.error({ key: operationKey, content: reason instanceof Error ? reason.message : `${record.sku}删除失败`, duration: 6 }); }
    finally { setActionId(null); }
  };

  const columns: NonNullable<TableProps<PromotionRecord>['columns']> = [
    { ...sortableColumn<PromotionRecord>('sku', 'SKU', query, 170), fixed: 'left', render: value => <Typography.Text copyable={{ text: String(value), onCopy: () => message.success({ key: `copy-sku-${String(value)}`, content: `SKU ${String(value)}已复制` }) }}>{String(value)}</Typography.Text> },
    { key: 'status', dataIndex: 'status', title: '状态', width: 105, render: (value: PromotionStatus) => <Tag color={statusColours[value]}>{promotionStatusLabel(value)}</Tag> },
    { ...sortableColumn<PromotionRecord>('promotion_name', '促销名称', query, 180), render: value => value || '历史未命名促销' },
    { ...sortableColumn<PromotionRecord>('discount_percent', '折扣', query, 80), render: value => <Tag color={discountTagColor(Number(value))}>-{value}%</Tag> },
    { key: 'asin', title: 'ASIN', width: 130, render: (_, row) => row.asin || row.asin_snapshot || '-' },
    { key: 'developer', title: '开发员', width: 110, render: (_, row) => row.developer || row.developer_snapshot || '未配置' },
    { ...sortableColumn<PromotionRecord>('start_date', '开始日期', query, 115) },
    { ...sortableColumn<PromotionRecord>('end_date', '结束日期', query, 115), render: value => value || '持续促销' },
    { ...sortableColumn<PromotionRecord>('average_7d', '7天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionRecord>('average_30d', '30天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionRecord>('daily_lift', '近7天与近30天日均差', query, 105), align: 'right', render: value => <span className={Number(value) < 0 ? 'promotion-negative' : 'promotion-positive'}>{Number(value) > 0 ? '+' : ''}{formatNumber(value)}</span> },
    { key: 'rule_key', dataIndex: 'rule_key', title: '命中策略', width: 205, render: (value, row) => promotionRuleLabel(String(value), row.discount_percent) },
    { key: 'source_missing', dataIndex: 'source_missing', title: '数据状态', width: 110, render: value => value ? <Tag color="warning">源数据缺失</Tag> : <Tag color="success">数据正常</Tag> },
    { key: 'action', title: '操作', fixed: 'right', width: 230, render: (_, row) => <Space size={2}>
      <Button size="small" type="link" icon={<EditOutlined />} disabled={actionId !== null} onClick={() => onEdit(row)}>编辑</Button>
      {row.status === 'active' && <Popconfirm title="将结束日期设置为今天？" description="今天仍会计入正在促销，明天自动结束。" onConfirm={() => void endToday(row)} okText="确认" cancelText="取消"><Button size="small" type="link" icon={<StopOutlined />} loading={actionId === row.id}>今日结束</Button></Popconfirm>}
      <Popconfirm title="删除这条促销记录？" description="仅删除当前活动记录，SKU 最近登记限时活动记录仍会保留。删除后无法恢复。" onConfirm={() => void remove(row)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}><Button size="small" type="link" danger disabled={actionId !== null}>删除</Button></Popconfirm>
    </Space> },
  ];

  return <Card className="promotion-table-card promotion-record-card">
    <div className="promotion-table-toolbar">
      <Space wrap>
        <ConfirmFilterSelect mode="single" ariaLabel="促销状态" value={status} normalizeValue={value => value || 'active'} onConfirm={value => { setStatus((value ? String(value) : 'active') as PromotionStatusFilter); setQuery(current => ({ ...current, page: 1 })); }} options={[{ value: 'active', label: '正在促销' }, { value: 'pending', label: '待开始' }, { value: 'ended', label: '已结束' }, { value: 'all', label: '全部状态' }]} placeholder="正在促销" style={{ width: 160 }} />
        <Input.Search value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={applySearch} allowClear placeholder="搜索 SKU、ASIN、开发员" style={{ width: 260 }} />
        <ConfirmFilterSelect mode="multiple" ariaLabel="开发员" value={query.developers} onConfirm={value => setQuery(current => ({ ...current, page: 1, developers: Array.isArray(value) ? value.map(String) : [] }))} placeholder="全部开发员" options={developerOptions.map(value => ({ value, label: value }))} style={{ minWidth: 220 }} />
        <FilterActions onReset={resetFilters} />
      </Space>
      <Space>
        <Button type="primary" icon={<TagsOutlined />} onClick={onManualAdd}>手动添加促销 SKU</Button>
        <Button icon={<DownloadOutlined />} disabled={loading} onClick={() => void downloadWithFeedback(exportUrl('/api/promotions/records/export.csv', query, { status }), 'promotions.csv', '促销记录')}>导出筛选结果</Button>
      </Space>
    </div>
    {error && <Alert className="section-load-error" type="error" showIcon message="促销记录加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    <Table<PromotionRecord>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={data?.rows || []}
      columns={columns}
      scroll={{ x: 1780 }}
      pagination={{ current: query.page, pageSize: query.pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 条` }}
      onChange={(pagination, _filters, sorter, extra) => {
        if (extra.action === 'sort') applyTableSort(sorter, setQuery);
        else setQuery(current => ({ ...current, page: pagination.pageSize !== current.pageSize ? 1 : pagination.current || 1, pageSize: pagination.pageSize || 50 }));
      }}
    />
  </Card>;
}

function ActualPricePanel({ refreshToken }: { refreshToken: number }) {
  const [rows, setRows] = useState<ListingObservation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searchDraft, setSearchDraft] = useState('');
  const [query, setQuery] = useState({ search: '', page: 1, pageSize: 30 });
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.pricingObservations({ search: query.search, page: query.page, page_size: query.pageSize }, controller.signal)
      .then(result => {
        const maxPage = Math.max(1, Math.ceil(result.total / query.pageSize));
        if (query.page > maxPage) {
          setQuery(current => ({ ...current, page: maxPage }));
          return;
        }
        setRows(result.rows);
        setTotal(result.total);
      })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '实际价格加载失败'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, refreshToken, reloadToken]);

  const applySearch = (value = searchDraft) => {
    setSearchDraft(value);
    setQuery(current => ({ ...current, search: value.trim(), page: 1 }));
  };
  const resetSearch = () => {
    setSearchDraft('');
    setQuery(current => ({ ...current, search: '', page: 1 }));
  };

  return <Card title="实际价格观察" extra={<Space wrap>
    <Input.Search allowClear value={searchDraft} placeholder="搜索 SKU / ASIN" onChange={event => setSearchDraft(event.target.value)} onSearch={applySearch} />
    <FilterActions onReset={resetSearch} />
    <Button icon={<ReloadOutlined />} onClick={() => setReloadToken(value => value + 1)}>刷新</Button>
  </Space>}>
    <Typography.Paragraph type="secondary">价格事件来自相邻 Listing 快照；“首次观察到”不等于精确改价时间。销量响应仅作方向参考，不代表因果。</Typography.Paragraph>
    {error && <Alert type="error" showIcon message="实际价格加载失败" description={error} action={<Button size="small" onClick={() => setReloadToken(value => value + 1)}>重试</Button>} />}
    <Table<ListingObservation>
      rowKey={row => `${row.sku}-${row.country}-${row.date}-${row.type}`}
      loading={loading}
      dataSource={rows}
      scroll={{ x: 1280 }}
      pagination={{ current: query.page, pageSize: query.pageSize, total, showSizeChanger: true, pageSizeOptions: [30, 50, 100, 200], showTotal: value => `共 ${value} 条` }}
      onChange={pagination => setQuery(current => ({ ...current, page: pagination.pageSize !== current.pageSize ? 1 : pagination.current || 1, pageSize: pagination.pageSize || 30 }))}
      columns={[
        { title: '观察日期', dataIndex: 'date', width: 110 },
        { title: 'SKU', dataIndex: 'sku', width: 180 },
        { title: 'ASIN', dataIndex: 'asin', width: 150 },
        { title: '站点', dataIndex: 'country', width: 70 },
        { title: '变化类型', dataIndex: 'type', width: 130, render: value => <Tag color={String(value).includes('涨') ? 'red' : 'green'}>{String(value)}</Tag> },
        { title: '前实际价', dataIndex: 'old_effective_price', render: value => value == null ? '无' : Number(value).toFixed(2) },
        { title: '后实际价', dataIndex: 'new_effective_price', render: value => value == null ? '无' : Number(value).toFixed(2) },
        { title: '较开售价', dataIndex: 'launch_change', render: value => value == null ? '—' : (Number(value) * 100).toFixed(1) + '%' },
        { title: '销量响应', render: (_, row) => row.sales_response?.status || '—' },
        { title: '核验', dataIndex: 'verification_status', render: value => <Tag>{String(value)}</Tag> },
      ]}
      locale={{ emptyText: '暂无价格变化事件' }}
    />
  </Card>;
}
export default function PromotionBoard({ active = true, routeVersion = 0, refreshVersion = 0 }: { active?: boolean; routeVersion?: number; refreshVersion?: number }) {
  const [refreshToken, setRefreshToken] = useState(0);
  const [dialog, setDialog] = useState<PromotionDialog>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [dataTab, setDataTab] = useState<PromotionDataTab>(() => promotionDataTabFromSearch(window.location.search));
  const externalRefreshVersion = useRef(refreshVersion);
  const externalRouteVersion = useRef(routeVersion);
  const refresh = useCallback(() => setRefreshToken(value => value + 1), []);

  useEffect(() => {
    const onPopState = () => { if (active) setDataTab(promotionDataTabFromSearch(window.location.search)); };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [active]);
  useEffect(() => {
    if (!active || externalRefreshVersion.current === refreshVersion) return;
    externalRefreshVersion.current = refreshVersion;
    refresh();
  }, [active, refresh, refreshVersion]);
  useEffect(() => {
    if (!active || externalRouteVersion.current === routeVersion) return;
    externalRouteVersion.current = routeVersion;
    setDataTab(promotionDataTabFromSearch(window.location.search));
  }, [active, routeVersion]);

  const changeDataTab = (value: string) => {
    const next = value as PromotionDataTab;
    if (!promotionDataTabs.includes(next) || next === dataTab) return;
    const url = new URL(window.location.href);
    url.searchParams.set('promotion_view', next);
    window.history.pushState({}, '', url);
    window.dispatchEvent(new Event('sales-dashboard-route-change'));
    setDataTab(next);
  };

  const tabItems = [
    { key: 'adjustments', label: '长期调价' },
    { key: 'records', label: '限时促销' },
    { key: 'history', label: 'SKU 历史' },
    { key: 'last-promotions', label: 'SKU 最近登记限时活动' },

    { key: 'candidates-10', label: '促销候选 -10%' },
    { key: 'candidates-8', label: '促销候选 -8%' },
    { key: 'candidates-5', label: '促销候选 -5%' },
  ];
  return <div className="promotion-board">
    <div className="page-heading promotion-page-heading">
      <div><Typography.Title level={2}>{dataTab === 'actual-prices' ? '实际价格观察' : '调价与促销'}</Typography.Title><Typography.Text type="secondary">{dataTab === 'actual-prices' ? '仅展示相邻 Listing 快照中的实际价格变化' : '长期调价与限时额外优惠独立登记；记录不会修改平台售价'}</Typography.Text></div>
      <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
    </div>
    {dataTab === 'actual-prices' ? <ActualPricePanel refreshToken={refreshToken} /> : <>
      <PromotionOverviewPanel refreshToken={refreshToken} onRefresh={refresh} />
      <Tabs className="promotion-data-tabs" activeKey={dataTab} onChange={changeDataTab} items={tabItems} />
      {dataTab === 'adjustments' && <PricingBatches refreshToken={refreshToken} onRegister={() => setManualOpen(true)} />}
      {dataTab === 'history' && <PricingHistory refreshToken={refreshToken} onRefresh={refresh} onRegister={() => setManualOpen(true)} />}
      {dataTab === 'records' && <RecordsTable refreshToken={refreshToken} onRefresh={refresh} onEdit={record => setDialog({ kind: 'edit', record })} onManualAdd={() => setManualOpen(true)} />}
      {dataTab === 'last-promotions' && <LastPromotionTable refreshToken={refreshToken} />}
      {dataTab === 'candidates-10' && <CandidateTable discount={10} refreshToken={refreshToken} onMark={skus => setDialog({ kind: 'create', skus, discount: 10 })} />}
      {dataTab === 'candidates-8' && <CandidateTable discount={8} refreshToken={refreshToken} onMark={skus => setDialog({ kind: 'create', skus, discount: 8 })} />}
      {dataTab === 'candidates-5' && <CandidateTable discount={5} refreshToken={refreshToken} onMark={skus => setDialog({ kind: 'create', skus, discount: 5 })} />}
    </>}
    <PromotionDateModal dialog={dialog?.kind === 'edit' ? dialog : null} onClose={() => setDialog(null)} onSaved={refresh} />
    <PricingRegistration open={manualOpen || dialog?.kind === 'create'} skus={dialog?.kind === 'create' ? dialog.skus : undefined} discount={dialog?.kind === 'create' ? dialog.discount : undefined} onClose={() => { setManualOpen(false); setDialog(null); }} onSaved={refresh} />
  </div>;
}
