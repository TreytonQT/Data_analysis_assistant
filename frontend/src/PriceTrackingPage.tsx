import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, DatePicker, Input, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, type TrackingPayload, type TrackingRow } from './api';
import type { PageLifecycleProps } from './pageLifecycle';
import PageHeading from './components/PageHeading';
import { PageLoading, SectionEmpty, SectionError } from './components/PageState';
import SkuDetailsDrawer from './components/SkuDetailsDrawer';
import ConfirmFilterSelect from './ConfirmFilterSelect';
import FilterActions from './FilterActions';
import { downloadWithFeedback } from './feedback';
import { quantity, rate, SkuIdentity, SourceDates } from './operationsPresentation';
import './ProductOperations.css';

type Query = { developers: string; country: string; band?: number; date_start?: string; date_end?: string; search: string; trend: string; sort_by: string; sort_order: 'asc' | 'desc'; page: number; page_size: number };
const initialQuery = (): Query => ({ developers: '', country: '', search: '', trend: 'all', sort_by: 'abs_t', sort_order: 'desc', page: 1, page_size: 30 });
export const directionFromUrl = () => new URLSearchParams(window.location.search).get('direction') === 'down' ? 'down' : 'up';

export default function PriceTrackingPage({ active = true, routeVersion = 0, refreshVersion = 0 }: PageLifecycleProps) {
  const [direction, setDirection] = useState(directionFromUrl);
  const [query, setQuery] = useState(initialQuery);
  const [searchDraft, setSearchDraft] = useState('');
  const [data, setData] = useState<TrackingPayload>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [detail, setDetail] = useState<TrackingRow | null>(null);
  const sequence = useRef(0);
  const params = useMemo(() => ({ ...query, direction }), [query, direction]);
  useEffect(() => {
    if (!active) { setDetail(null); return; }
    const next = directionFromUrl();
    if (next !== direction) { setData(undefined); setDetail(null); setDirection(next); setQuery(current => ({ ...current, band: undefined, page: 1 })); }
  }, [active, routeVersion, direction]);
  useEffect(() => {
    if (!active || direction !== directionFromUrl()) return;
    const controller = new AbortController(); const id = ++sequence.current; setLoading(true); setError('');
    api.tracking(params, controller.signal).then(result => {
      if (controller.signal.aborted || id !== sequence.current) return;
      const maxPage = Math.max(1, Math.ceil(result.total / query.page_size));
      if (query.page > maxPage) { setQuery(current => ({ ...current, page: maxPage })); return; }
      setData(result);
    }).catch(reason => { if (!controller.signal.aborted && id === sequence.current) setError(reason instanceof Error ? reason.message : '价格追踪加载失败'); })
      .finally(() => { if (!controller.signal.aborted && id === sequence.current) setLoading(false); });
    return () => { controller.abort(); sequence.current += 1; };
  }, [active, params, direction, query.page, query.page_size, refreshVersion, routeVersion, retry]);
  useEffect(() => {
    if (!active) return;
    let day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const timer = window.setInterval(() => {
      const next = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
      if (next !== day) { day = next; setRetry(value => value + 1); }
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const apply = (values: Partial<Query>) => setQuery(current => ({ ...current, ...values, page: 1 }));
  const exportParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && key !== 'page' && key !== 'page_size') exportParams.set(key, String(value)); });
  const title = direction === 'up' ? '涨价追踪' : '降价追踪';
  const columns: ColumnsType<TrackingRow> = [
    { title: '产品 / 国家', key: 'identity', width: 265, render: (_, row) => <SkuIdentity row={row} country={row.country} onOpen={() => setDetail(row)} /> },
    { title: '前 → 后实际价', width: 180, render: (_, row) => <div className="ops-price-cell"><strong>{quantity(row.old_effective_price, 2)} <span>→</span> {quantity(row.new_effective_price, 2)}</strong><div className="ops-secondary">{row.currency} · {rate(row.change)} · {row.date.slice(5)}</div></div> },
    { title: '站点日均 7天 / 30天', width: 160, align: 'right', render: (_, row) => <Tooltip title={<div>站点7天：{row.units_7_source || '暂无完整证据'}；30天：{row.units_30_source || '暂无完整证据'}<br />SKU参考：{row.sku_sales_source || '暂无'}，上传快照 {row.sku_sales_snapshot || '未知'}。跨国汇总不拆分到各国家。</div>}><div className="ops-numeric">{quantity(row.units_7 == null ? null : row.units_7 / 7, 2)} <span className="ops-secondary">/ {quantity(row.units_30 == null ? null : row.units_30 / 30, 2)}</span>
      {(row.units_7 == null || row.units_30 == null) && (row.sku_units_7 != null || row.sku_units_30 != null) && <div className="ops-secondary">SKU总量 {quantity(row.sku_units_7)} / {quantity(row.sku_units_30)}</div>}
    </div></Tooltip> },
    { title: <Tooltip title="站点T = 7天日均 − 30天日均；SKU汇总参考不参与此排名。当前趋势不表示调价造成的增量">站点 T（件/天）</Tooltip>, width: 130, align: 'right', render: (_, row) => <div className="ops-t-value"><strong>{row.t_value != null && row.t_value > 0 ? '+' : ''}{quantity(row.t_value, 2)}</strong><span>{row.t_value == null ? row.observation === '销量待更新' ? '站点销量待更新' : '站点证据缺失' : row.t_value > 0 ? '销量上升' : row.t_value < 0 ? '销量下降' : '销量持平'}</span>{row.t_value == null && row.sku_t_value != null && <div className="ops-secondary">SKU参考T {quantity(row.sku_t_value, 2)}</div>}</div> },
  ];
  const maxCount = Math.max(1, ...(data?.buckets.map(bucket => bucket.count) || []));
  return <div className="ops-page ops-tracking">
    <PageHeading title={title} description="默认查看截至最新快照的近30天变价，可调整观察日期。" actions={<Button icon={<ReloadOutlined />} onClick={() => setRetry(value => value + 1)} loading={loading}>刷新</Button>} />
    <div className="ops-filter-bar">
      <ConfirmFilterSelect ariaLabel="开发员筛选" selectionUnit="人" mode="multiple" value={query.developers ? query.developers.split(',') : []} options={(data?.developers || []).map(value => ({ value, label: value }))} onConfirm={value => apply({ developers: (Array.isArray(value) ? value : []).join(',') })} placeholder="全部开发员" />
      <ConfirmFilterSelect mode="single" ariaLabel="国家筛选" value={query.country || undefined} options={['DE', 'FR', 'ES', 'IT'].map(value => ({ value, label: value }))} onConfirm={value => apply({ country: String(value || '') })} placeholder="全部国家" />
      <ConfirmFilterSelect mode="single" ariaLabel="销量趋势筛选" placeholder="全部销量趋势" normalizeValue={value => value || 'all'} value={query.trend} options={[{ value: 'all', label: '全部销量趋势' }, { value: 'up', label: '销量上升' }, { value: 'down', label: '销量下降' }, { value: 'flat', label: '销量持平' }, { value: 'missing', label: '销量证据缺失' }]} onConfirm={value => apply({ trend: String(value || 'all') })} />
      <DatePicker.RangePicker aria-label="变价观察日期范围" value={query.date_start && query.date_end ? [dayjs(query.date_start), dayjs(query.date_end)] : null} onChange={value => apply({ date_start: value?.[0]?.format('YYYY-MM-DD'), date_end: value?.[1]?.format('YYYY-MM-DD') })} />
      <Input.Search aria-label="搜索品名、SKU或ASIN" placeholder="品名 / SKU / ASIN" value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={value => apply({ search: value.trim() })} allowClear className="ops-search" />
      <FilterActions onReset={() => { setQuery(initialQuery()); setSearchDraft(''); }} />
    </div>
    {error && <SectionError title="价格追踪加载失败" error={error} onRetry={() => setRetry(value => value + 1)} />}
    {!data && loading && <PageLoading label="正在分析实际变价与当前销量…" />}
    {data && <>
      <div className="ops-tracking-context"><div><b>{quantity(data.metrics.sku_count)}</b> 涉及SKU <span> / </span><b>{quantity(data.metrics.records)}</b> 站点记录 <span>·</span> 销量截至 {data.as_of || '缺失'}</div><SourceDates sources={data.sources} salesAsOf={data.as_of} /></div>
      {data.metrics.records > 0 && data.metrics.missing === data.metrics.records && <Alert className="ops-coverage-alert" type="info" showIcon message="当前范围站点T暂缺，可查看行内运营表SKU汇总参考；参考不计入国家排名，缺失不按0计算。" />}
      <div className="ops-tracking-layout">
        <aside className="ops-distribution" aria-label="价格变动幅度分布"><div className="ops-section-heading"><h2>{direction === 'up' ? '涨幅' : '降幅'}分布</h2><Button type="text" size="small" disabled={query.band === undefined} onClick={() => apply({ band: undefined })}>全部</Button></div>
          <p className="ops-secondary">每5个百分点一档 · {quantity(data.distribution_total)}条</p>
          <div className="ops-distribution-legend"><span className="ops-legend-up">上升</span><span className="ops-legend-down">下降</span><span className="ops-legend-flat">持平 / 缺失</span></div>
          <div className="ops-distribution-bars">{data.buckets.map(bucket => <Tooltip key={bucket.band} title={`销量上升 ${bucket.up} · 下降 ${bucket.down} · 持平 ${bucket.flat} · 缺失 ${bucket.missing}；平均T ${quantity(bucket.mean_t, 2)}`}>
            <button className={`ops-distribution-bin ${query.band === bucket.band ? 'ops-distribution-bin-selected' : ''}`} aria-pressed={query.band === bucket.band} onClick={() => apply({ band: query.band === bucket.band ? undefined : bucket.band })}>
              <span className="ops-bin-label">{bucket.band}–{bucket.band + 5}%</span><b>{quantity(bucket.count)}</b>
              <span className="ops-bin-track"><span className="ops-bin-fill" style={{ width: `${bucket.count / maxCount * 100}%` }}>{(['up', 'down', 'flat', 'missing'] as const).map(kind => <i key={kind} className={`ops-bin-${kind}`} style={{ flex: bucket[kind] }} />)}</span></span>
              <span className="ops-bin-mean">平均T {quantity(bucket.mean_t, 2)}</span>
            </button>
          </Tooltip>)}</div>
          {!data.buckets.length && <SectionEmpty description="当前条件暂无实际变价" />}
        </aside>
        <section className="ops-ranking" aria-label="SKU销量变化排名"><div className="ops-section-heading"><div><h2>销量变化排名</h2><span className="ops-secondary">{query.band === undefined ? '全部幅度' : `${query.band}–${query.band + 5}%`} · 每SKU＋ASIN＋国家最新一次变价</span></div><Space>
          <ConfirmFilterSelect mode="single" ariaLabel="销量排名方式" placeholder="变化幅度最大" normalizeValue={value => value || 'abs'} value={query.sort_by === 't_value' ? (query.sort_order === 'asc' ? 'down' : 'up') : 'abs'} options={[{ value: 'abs', label: '变化幅度最大' }, { value: 'up', label: '销量上升最多' }, { value: 'down', label: '销量下降最多' }]} onConfirm={value => apply(value === 'down' ? { sort_by: 't_value', sort_order: 'asc' } : value === 'up' ? { sort_by: 't_value', sort_order: 'desc' } : { sort_by: 'abs_t', sort_order: 'desc' })} />
          <Button icon={<DownloadOutlined />} onClick={() => void downloadWithFeedback('/api/product-operations/prices/export.csv?' + exportParams, `price-tracking-${direction}.csv`, '站点追踪清单')}>导出</Button>
        </Space></div>
          <Table<TrackingRow> size="small" tableLayout="fixed" rowKey={row => JSON.stringify([row.sku, row.asin, row.country])} columns={columns} dataSource={data.rows} loading={loading} scroll={{ x: 735 }} pagination={{ current: query.page, pageSize: query.page_size, total: data.total, showSizeChanger: true, pageSizeOptions: [30, 50, 100, 200], showTotal: total => `${total}条站点记录`, onChange: (page, page_size) => setQuery(current => ({ ...current, page: page_size === current.page_size ? page : 1, page_size })) }} />
        </section>
      </div>
      <div className="ops-tracking-notes"><p>T = 7天日均 − 30天日均。价格为买家实际总价；排名反映当前销量趋势，请结合利润、库存和历史核查。</p><p>站点T缺失 {quantity(data.metrics.missing)} 条，其中 {quantity(data.metrics.sku_reference || 0)} 条有SKU汇总参考。参考来自运营原始表，不计入站点排名或分布统计。</p><p>已覆盖快照 {data.coverage.start || '暂无'}～{data.coverage.end || '暂无'} · 保留180天；无法自动补回未上传的价格历史。</p></div>
      {!!data.warnings.length && <Alert type="warning" showIcon message={data.warnings.join('；')} />}
    </>}
    <SkuDetailsDrawer sku={active ? detail?.sku || null : null} initialAsin={detail?.asin} initialCountry={detail?.country} onClose={() => setDetail(null)} refreshVersion={refreshVersion} />
  </div>;
}
