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
  Select,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CopyOutlined,
  DownloadOutlined,
  EditOutlined,
  ReloadOutlined,
  StopOutlined,
  TagsOutlined,
} from '@ant-design/icons';
import type { TableProps } from 'antd';
import {
  api,
  type PromotionCandidate,
  type PromotionDateInput,
  type PromotionDiscount,
  type PromotionDiscountSummary,
  type PromotionOverview,
  type PromotionPage,
  type PromotionRecord,
  type PromotionStatus,
  type PromotionStatusFilter,
} from './api';

type ListQuery = {
  page: number;
  pageSize: number;
  search: string;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  developers: string[];
};

type PromotionFormValues = { start_date: Dayjs; end_date?: Dayjs | null };
type PromotionDialog = { kind: 'create'; skus: string[] } | { kind: 'edit'; record: PromotionRecord } | null;

const defaultQuery: ListQuery = { page: 1, pageSize: 50, search: '', developers: [] };
const statusColours: Record<PromotionStatus, string> = { pending: 'gold', active: 'green', ended: 'default' };

export function promotionStatusLabel(status: PromotionStatus) {
  return status === 'active' ? '正在促销' : status === 'pending' ? '待开始' : '已结束';
}

export function promotionRuleLabel(ruleKey: string, discount: number) {
  const labels: Record<string, string> = {
    sales_le_10: '可售≥20，90天销量≤10',
    sales_11_20: '可售≥20，90天销量11–20',
    sales_21_30: '可售≥20，90天销量21–30',
    aged_90d: '90天以上库存兜底',
  };
  return labels[ruleKey] || (discount === 10 ? '可售≥20，90天销量≤10' : discount === 8 ? '可售≥20，90天销量≤20' : '建议降价促销');
}

export function skuCopyText(skus: string[]) {
  return [...new Set(skus.map(value => value.trim()).filter(Boolean))].join('\n');
}

export async function writeClipboard(text: string) {
  if (!text) throw new Error('没有可复制的 SKU');
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return; }
    catch { /* 使用本地旧版浏览器的同步复制能力继续尝试。 */ }
  }
  const input = document.createElement('textarea');
  input.value = text; input.readOnly = true; input.style.position = 'fixed'; input.style.opacity = '0';
  document.body.appendChild(input); input.select();
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('剪贴板写入失败，请检查浏览器权限后重试');
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

function download(url: string) {
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  document.body.appendChild(link);
  link.click();
  link.remove();
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

function LiftSummaryChart({ rows }: { rows: PromotionDiscountSummary[] }) {
  const sorted = ([10, 8, 5] as PromotionDiscount[]).map(discount => rows.find(row => row.discount_percent === discount) || {
    discount_percent: discount, sku_count: 0, average_7d: 0, average_30d: 0, daily_lift: 0,
  });
  const maximum = Math.max(...sorted.map(row => Math.abs(Number(row.daily_lift) || 0)), 1);
  return <div className="promotion-lift-chart" role="img" aria-label="各折扣日均销量提升对比">
    {sorted.map(row => {
      const lift = Number(row.daily_lift) || 0;
      return <div className="promotion-lift-row" key={row.discount_percent}>
        <Tag color={row.discount_percent === 10 ? 'red' : row.discount_percent === 8 ? 'orange' : 'blue'}>-{row.discount_percent}%</Tag>
        <div className="promotion-lift-track"><i className={lift >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.abs(lift) / maximum * 50}%` }} /></div>
        <strong className={lift < 0 ? 'promotion-negative' : 'promotion-positive'}>{lift > 0 ? '+' : ''}{formatNumber(lift)}</strong>
        <Typography.Text type="secondary">{formatNumber(row.sku_count, 0)} 个 SKU</Typography.Text>
      </div>;
    })}
  </div>;
}

function PromotionOverviewPanel({ refreshToken }: { refreshToken: number }) {
  const [data, setData] = useState<PromotionOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.promotionOverview(controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '促销汇总加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshToken, retry]);

  if (loading && !data) return <Card className="promotion-overview-card"><Skeleton active paragraph={{ rows: 4 }} /></Card>;
  return <>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="促销汇总加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    {data && <>
      <div className="promotion-metric-grid">
        <Card><Statistic title="正在促销 SKU" value={formatNumber(data.active_sku_count, 0)} suffix="个" /></Card>
        <Card><Statistic title="7天日均销量合计" value={formatNumber(data.average_7d_total)} /></Card>
        <Card><Statistic title="30天日均销量合计" value={formatNumber(data.average_30d_total)} /></Card>
        <Card><Statistic title="日均销量提升合计" value={`${Number(data.daily_lift_total) > 0 ? '+' : ''}${formatNumber(data.daily_lift_total)}`} valueStyle={{ color: Number(data.daily_lift_total) < 0 ? '#ef4444' : '#16a34a' }} /></Card>
        <Card><Statistic title="单 SKU 平均提升" value={`${Number(data.daily_lift_average) > 0 ? '+' : ''}${formatNumber(data.daily_lift_average)}`} valueStyle={{ color: Number(data.daily_lift_average) < 0 ? '#ef4444' : '#16a34a' }} /></Card>
      </div>
      {Number(data.source_missing_count) > 0 && <Alert className="promotion-source-warning" type="warning" showIcon message={`${formatNumber(data.source_missing_count, 0)} 个促销 SKU 已不在当前源数据中`} description="记录仍会保留，但不会计入上方销量提升汇总。" />}
      <Card className="promotion-overview-card" title="各折扣日均销量提升" extra={formatUpdatedAt(data.updated_at) ? <Typography.Text type="secondary">数据更新时间 {formatUpdatedAt(data.updated_at)}</Typography.Text> : null}>
        <LiftSummaryChart rows={data.by_discount || []} />
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
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    setData(current => current ? { ...current, rows: [] } : null);
    api.promotionCandidates(discount, queryParams(query) as Parameters<typeof api.promotionCandidates>[1], controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '候选 SKU 加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [discount, query.page, query.pageSize, query.search, query.sortBy, query.sortOrder, query.developers.join(','), refreshToken, retry]);

  useEffect(() => setSelected([]), [refreshToken]);

  const copy = async (skus: string[]) => {
    try { await writeClipboard(skuCopyText(skus)); message.success(`已复制 ${skus.length} 个 SKU`); }
    catch (reason) { message.error(reason instanceof Error ? reason.message : '复制失败，请重试'); }
  };
  const copyAll = async () => {
    setCopyingAll(true);
    try {
      const text = await api.promotionCandidateSkus(discount, { search: query.search || undefined, developers: query.developers.length ? query.developers.join(',') : undefined, sort_by: query.sortBy, sort_order: query.sortOrder });
      const count = text.split(/\r?\n/).filter(Boolean).length;
      await writeClipboard(text.trim());
      message.success(`已复制当前筛选下全部 ${count} 个 SKU`);
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '复制失败，请重试'); }
    finally { setCopyingAll(false); }
  };

  const columns: NonNullable<TableProps<PromotionCandidate>['columns']> = [
    { ...sortableColumn<PromotionCandidate>('sku', 'SKU', query, 170), fixed: 'left', render: value => <Typography.Text copyable={{ text: String(value) }}>{String(value)}</Typography.Text> },
    { ...sortableColumn<PromotionCandidate>('asin', 'ASIN', query, 130), render: value => value || '-' },
    { ...sortableColumn<PromotionCandidate>('developer', '开发员', query, 110), render: value => value || '未配置' },
    { ...sortableColumn<PromotionCandidate>('available_inventory', '可售库存', query, 110), align: 'right', render: value => formatNumber(value, 0) },
    { ...sortableColumn<PromotionCandidate>('sales_90d', '90天销量', query, 110), align: 'right', render: value => formatNumber(value, 2) },
    { ...sortableColumn<PromotionCandidate>('aged_inventory_90d', '90天以上库存', query, 130), align: 'right', render: value => formatNumber(value, 0) },
    { ...sortableColumn<PromotionCandidate>('average_7d', '7天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionCandidate>('average_30d', '30天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionCandidate>('daily_lift', '日均提升', query, 110), align: 'right', render: value => <span className={Number(value) < 0 ? 'promotion-negative' : 'promotion-positive'}>{Number(value) > 0 ? '+' : ''}{formatNumber(value)}</span> },
    { key: 'discount_percent', dataIndex: 'discount_percent', title: '建议折扣', width: 100, render: value => <Tag color={discount === 10 ? 'red' : discount === 8 ? 'orange' : 'blue'}>-{value}%</Tag> },
    { key: 'rule_key', dataIndex: 'rule_key', title: '命中策略', width: 210, render: value => promotionRuleLabel(String(value), discount) },
    { key: 'action', title: '操作', fixed: 'right', width: 110, render: (_, row) => <Button size="small" type="link" icon={<TagsOutlined />} onClick={() => onMark([row.sku])}>标记促销</Button> },
  ];

  const applySearch = (value: string) => {
    setSelected([]);
    setQuery(current => ({ ...current, page: 1, search: value.trim() }));
  };
  return <Card className="promotion-table-card" title={<Space><Tag color={discount === 10 ? 'red' : discount === 8 ? 'orange' : 'blue'}>-{discount}%</Tag><span>促销候选</span><Typography.Text type="secondary">共 {formatNumber(data?.total ?? 0, 0)} 个</Typography.Text></Space>}>
    <div className="promotion-table-toolbar">
      <Space wrap>
        <Input.Search value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={applySearch} allowClear placeholder="搜索 SKU、ASIN、开发员" style={{ width: 260 }} />
        <Select mode="multiple" maxTagCount="responsive" value={query.developers} onChange={values => { setSelected([]); setQuery(current => ({ ...current, page: 1, developers: values })); }} allowClear placeholder="筛选开发员" options={(data?.developers || []).map(value => ({ value, label: value }))} style={{ minWidth: 220 }} />
      </Space>
      <Space wrap>
        <Button icon={<CopyOutlined />} disabled={!selected.length} onClick={() => void copy(selected.map(String))}>复制所选（{selected.length}）</Button>
        <Button icon={<CopyOutlined />} loading={copyingAll} onClick={() => void copyAll()}>复制筛选下全部</Button>
        <Button icon={<DownloadOutlined />} onClick={() => download(exportUrl(`/api/promotions/candidates/${discount}/export.csv`, query))}>导出 CSV</Button>
        <Button type="primary" icon={<TagsOutlined />} disabled={!selected.length} onClick={() => onMark(selected.map(String))}>批量标记促销</Button>
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

function PromotionDateModal({ dialog, onClose, onSaved }: { dialog: PromotionDialog; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<PromotionFormValues>();
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!dialog) return;
    form.resetFields();
    form.setFieldsValue(dialog.kind === 'edit' ? {
      start_date: dayjs(dialog.record.start_date), end_date: dialog.record.end_date ? dayjs(dialog.record.end_date) : null,
    } : { start_date: dayjs(), end_date: null });
  }, [dialog, form]);

  const close = () => { if (!savingRef.current) { form.resetFields(); onClose(); } };
  const submit = async () => {
    if (!dialog || savingRef.current) return;
    savingRef.current = true;
    let values: PromotionFormValues;
    try { values = await form.validateFields(); }
    catch { savingRef.current = false; return; }
    setSaving(true);
    const payload: PromotionDateInput = { start_date: values.start_date.format('YYYY-MM-DD'), end_date: values.end_date ? values.end_date.format('YYYY-MM-DD') : null };
    try {
      if (dialog.kind === 'edit') await api.updatePromotion(dialog.record.id, payload);
      else await api.createPromotions(dialog.skus, payload);
      message.success(dialog.kind === 'edit' ? '促销日期已更新' : `已标记 ${dialog.skus.length} 个促销 SKU`);
      form.resetFields(); onClose(); onSaved();
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '保存失败，请重试'); }
    finally { savingRef.current = false; setSaving(false); }
  };

  const skus = dialog?.kind === 'create' ? dialog.skus : [];
  return <Modal
    title={dialog?.kind === 'edit' ? `编辑促销日期 · ${dialog.record.sku}` : '标记正在促销'}
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
    {dialog?.kind === 'create' && <Alert className="promotion-dialog-summary" type="info" showIcon message={`将标记 ${skus.length} 个 SKU`} description={<Typography.Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }} copyable={{ text: skuCopyText(skus) }}>{skus.join('、')}</Typography.Paragraph>} />}
    <Form form={form} layout="vertical" preserve={false}>
      <Form.Item name="start_date" label="开始日期" rules={[{ required: true, message: '请选择开始日期' }]}><DatePicker allowClear={false} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="end_date" label="结束日期（可不填）" dependencies={['start_date']} rules={[({ getFieldValue }) => ({ validator(_, value?: Dayjs | null) { const start = getFieldValue('start_date') as Dayjs | undefined; return value && start && value.isBefore(start, 'day') ? Promise.reject(new Error('结束日期不能早于开始日期')) : Promise.resolve(); } })]}><DatePicker placeholder="不填表示持续促销" style={{ width: '100%' }} /></Form.Item>
      <Typography.Text type="secondary">结束日期当天仍计为“正在促销”，次日自动转为“已结束”。</Typography.Text>
    </Form>
  </Modal>;
}

function RecordsTable({ refreshToken, onRefresh, onEdit }: { refreshToken: number; onRefresh: () => void; onEdit: (record: PromotionRecord) => void }) {
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
    setData(current => current ? { ...current, rows: [] } : null);
    api.promotionRecords({ ...queryParams(query), status } as Parameters<typeof api.promotionRecords>[0], controller.signal).then(setData).catch(reason => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '促销记录加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [status, query.page, query.pageSize, query.search, query.sortBy, query.sortOrder, query.developers.join(','), refreshToken, retry]);

  const endToday = async (record: PromotionRecord) => {
    setActionId(record.id);
    try {
      await api.updatePromotion(record.id, { start_date: record.start_date, end_date: dayjs().format('YYYY-MM-DD') });
      message.success('已将结束日期设为今天'); onRefresh();
    } catch (reason) { message.error(reason instanceof Error ? reason.message : '结束促销失败'); }
    finally { setActionId(null); }
  };
  const remove = async (record: PromotionRecord) => {
    setActionId(record.id);
    try { await api.deletePromotion(record.id); message.success('促销记录已删除'); onRefresh(); }
    catch (reason) { message.error(reason instanceof Error ? reason.message : '删除失败'); }
    finally { setActionId(null); }
  };

  const columns: NonNullable<TableProps<PromotionRecord>['columns']> = [
    { ...sortableColumn<PromotionRecord>('sku', 'SKU', query, 170), fixed: 'left', render: value => <Typography.Text copyable={{ text: String(value) }}>{String(value)}</Typography.Text> },
    { key: 'status', dataIndex: 'status', title: '状态', width: 105, render: (value: PromotionStatus) => <Tag color={statusColours[value]}>{promotionStatusLabel(value)}</Tag> },
    { ...sortableColumn<PromotionRecord>('discount_percent', '折扣', query, 80), render: value => <Tag color={Number(value) === 10 ? 'red' : Number(value) === 8 ? 'orange' : 'blue'}>-{value}%</Tag> },
    { key: 'asin', title: 'ASIN', width: 130, render: (_, row) => row.asin || row.asin_snapshot || '-' },
    { key: 'developer', title: '开发员', width: 110, render: (_, row) => row.developer || row.developer_snapshot || '未配置' },
    { ...sortableColumn<PromotionRecord>('start_date', '开始日期', query, 115) },
    { ...sortableColumn<PromotionRecord>('end_date', '结束日期', query, 115), render: value => value || '持续促销' },
    { ...sortableColumn<PromotionRecord>('average_7d', '7天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionRecord>('average_30d', '30天日均', query, 105), align: 'right', render: value => formatNumber(value) },
    { ...sortableColumn<PromotionRecord>('daily_lift', '日均提升', query, 105), align: 'right', render: value => <span className={Number(value) < 0 ? 'promotion-negative' : 'promotion-positive'}>{Number(value) > 0 ? '+' : ''}{formatNumber(value)}</span> },
    { key: 'rule_key', dataIndex: 'rule_key', title: '命中策略', width: 205, render: (value, row) => promotionRuleLabel(String(value), row.discount_percent) },
    { key: 'source_missing', dataIndex: 'source_missing', title: '数据状态', width: 110, render: value => value ? <Tag color="warning">源数据缺失</Tag> : <Tag color="success">数据正常</Tag> },
    { key: 'action', title: '操作', fixed: 'right', width: 230, render: (_, row) => <Space size={2}>
      <Button size="small" type="link" icon={<EditOutlined />} disabled={actionId !== null} onClick={() => onEdit(row)}>编辑</Button>
      {row.status === 'active' && <Popconfirm title="将结束日期设置为今天？" description="今天仍会计入正在促销，明天自动结束。" onConfirm={() => void endToday(row)} okText="确认" cancelText="取消"><Button size="small" type="link" icon={<StopOutlined />} loading={actionId === row.id}>今日结束</Button></Popconfirm>}
      <Popconfirm title="删除这条促销记录？" description="仅用于删除误建记录，删除后无法恢复。" onConfirm={() => void remove(row)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}><Button size="small" type="link" danger disabled={actionId !== null}>删除</Button></Popconfirm>
    </Space> },
  ];

  return <Card className="promotion-table-card promotion-record-card" title={<Space><span>已开促销 SKU</span><Typography.Text type="secondary">共 {formatNumber(data?.total ?? 0, 0)} 条</Typography.Text></Space>}>
    <div className="promotion-table-toolbar">
      <Space wrap>
        <Select value={status} onChange={value => { setStatus(value); setQuery(current => ({ ...current, page: 1 })); }} options={[{ value: 'active', label: '正在促销' }, { value: 'pending', label: '待开始' }, { value: 'ended', label: '已结束' }, { value: 'all', label: '全部状态' }]} style={{ width: 140 }} />
        <Input.Search value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={value => setQuery(current => ({ ...current, page: 1, search: value.trim() }))} allowClear placeholder="搜索 SKU、ASIN、开发员" style={{ width: 260 }} />
        <Select mode="multiple" maxTagCount="responsive" value={query.developers} onChange={values => setQuery(current => ({ ...current, page: 1, developers: values }))} allowClear placeholder="筛选开发员" options={(data?.developers || []).map(value => ({ value, label: value }))} style={{ minWidth: 220 }} />
      </Space>
      <Button icon={<DownloadOutlined />} onClick={() => download(exportUrl('/api/promotions/records/export.csv', query, { status }))}>导出 CSV</Button>
    </div>
    {error && <Alert className="section-load-error" type="error" showIcon message="促销记录加载失败" description={error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
    <Table<PromotionRecord>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={data?.rows || []}
      columns={columns}
      scroll={{ x: 1600 }}
      pagination={{ current: query.page, pageSize: query.pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 条` }}
      onChange={(pagination, _filters, sorter, extra) => {
        if (extra.action === 'sort') applyTableSort(sorter, setQuery);
        else setQuery(current => ({ ...current, page: pagination.pageSize !== current.pageSize ? 1 : pagination.current || 1, pageSize: pagination.pageSize || 50 }));
      }}
    />
  </Card>;
}

export default function PromotionBoard() {
  const [refreshToken, setRefreshToken] = useState(0);
  const [dialog, setDialog] = useState<PromotionDialog>(null);
  const refresh = useCallback(() => setRefreshToken(value => value + 1), []);
  return <div className="promotion-board">
    <div className="page-heading promotion-page-heading">
      <div><Typography.Title level={2}>促销提醒</Typography.Title><Typography.Text type="secondary">自动识别动销折扣候选，并跟踪正在促销 SKU 的日均销量变化</Typography.Text></div>
      <Button icon={<ReloadOutlined />} onClick={refresh}>刷新全部</Button>
    </div>
    <PromotionOverviewPanel refreshToken={refreshToken} />
    <RecordsTable refreshToken={refreshToken} onRefresh={refresh} onEdit={record => setDialog({ kind: 'edit', record })} />
    <div className="promotion-candidate-heading"><Typography.Title level={3}>待标记促销候选</Typography.Title><Typography.Text type="secondary">正在促销和待开始的 SKU 已自动排除；已结束后如仍满足策略会重新出现。</Typography.Text></div>
    {([10, 8, 5] as PromotionDiscount[]).map(discount => <CandidateTable key={discount} discount={discount} refreshToken={refreshToken} onMark={skus => setDialog({ kind: 'create', skus })} />)}
    <PromotionDateModal dialog={dialog} onClose={() => setDialog(null)} onSaved={refresh} />
  </div>;
}
