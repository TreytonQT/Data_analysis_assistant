import { useEffect, useRef, useState } from 'react';
import { Alert, Descriptions, Drawer, Segmented, Select, Table, Tabs, Typography } from 'antd';
import { api, type OperationsDetail, type OperationsSeries } from '../api';
import { PageLoading, SectionEmpty, SectionError } from './PageState';
import ChartAxisTooltip, { useChartAxisTooltip } from './ChartAxisTooltip';
import SkuImagePreview from '../SkuImagePreview';
import { money, quantity, rate, RiskTags, SourceDates } from '../operationsPresentation';

const recordLabels: Record<string, string> = { promotion_name: '促销名称', batch_name: '调价批次', discount_percent: '登记降幅（%）', start_date: '开始日期', end_date: '结束日期', effective_date: '生效日期', asin_snapshot: '登记ASIN', developer_snapshot: '登记开发员', reason: '登记原因', voided_at: '作废时间', void_reason: '作废原因', created_at: '登记时间', updated_at: '更新时间' };

export function ObservationChart({ rows, field, title }: { rows: OperationsSeries['rows']; field: 'units' | 'price'; title: string }) {
  const width = 720;
  const height = 166;
  const top = 16;
  const bottom = 135;
  const known = rows.flatMap(row => row[field] == null ? [] : [row[field] as number]);
  const max = Math.max(1, ...known);
  const points = rows.map((row, index) => ({ x: 40 + index / Math.max(1, rows.length - 1) * 660, y: bottom - (row[field] ?? 0) / max * (bottom - top) }));
  const axis = useChartAxisTooltip({ points, width, height, revision: rows });
  let path = '';
  let previous = false;
  rows.forEach((row, index) => {
    if (row[field] == null) { previous = false; return; }
    path += `${previous ? 'L' : 'M'}${points[index].x},${points[index].y} `;
    previous = true;
  });
  const selected = axis.activeIndex == null ? null : rows[axis.activeIndex];
  return <section className="ops-observation-chart"><div className="ops-section-heading"><h3>{title}</h3><span>{field === 'units' ? '件 / 天' : '所选站点币种'}</span></div>
    {!known.length && <Typography.Text type="secondary">此范围暂无已观察数据</Typography.Text>}
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title}，左右方向键查看每日数据`} {...axis.svgProps}>
      {[0, .5, 1].map(fraction => <g key={fraction}><line x1="40" x2="700" y1={bottom - fraction * (bottom - top)} y2={bottom - fraction * (bottom - top)} className="ops-chart-grid" /><text x="32" y={bottom - fraction * (bottom - top) + 4} textAnchor="end">{quantity(max * fraction, 1)}</text></g>)}
      <path d={path} className="ops-chart-line" />
      {rows.map((row, index) => row[field] == null ? null : <circle key={row.date} cx={points[index].x} cy={points[index].y} r={field === 'price' ? 2 : 1.4} className="ops-chart-dot" />)}
      {field === 'price' && rows.map((row, index) => row.event ? <line key={row.date} x1={points[index].x} x2={points[index].x} y1={top} y2={bottom} className="ops-chart-event" /> : null)}
      {[0, Math.floor(rows.length / 2), rows.length - 1].filter((value, index, values) => value >= 0 && values.indexOf(value) === index).map(index => <text key={index} x={points[index]?.x} y="158" textAnchor={index === 0 ? 'start' : index === rows.length - 1 ? 'end' : 'middle'}>{rows[index]?.date.slice(5)}</text>)}
      {axis.activeIndex != null && <line x1={points[axis.activeIndex].x} x2={points[axis.activeIndex].x} y1={top} y2={bottom} className="ops-chart-focus" />}
      <rect x="32" y="0" width="680" height="145" fill="transparent" {...axis.hitAreaProps} />
    </svg>
    <ChartAxisTooltip id={axis.tooltipId} anchor={axis.anchor} title={selected?.date} items={[{ label: title, value: quantity(selected?.[field], field === 'price' ? 2 : 0) }]} footer={selected?.event ? '此日观察到实际变价' : undefined} />
  </section>;
}

export default function SkuDetailsDrawer({ sku, onClose, refreshVersion = 0, initialAsin, initialCountry }: { sku: string | null; onClose: () => void; refreshVersion?: number; initialAsin?: string; initialCountry?: string }) {
  const [data, setData] = useState<OperationsDetail>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('facts');
  const [market, setMarket] = useState('');
  const [days, setDays] = useState(30);
  const [discardScope, setDiscardScope] = useState('90');
  const [series, setSeries] = useState<OperationsSeries>();
  const [seriesError, setSeriesError] = useState('');
  const [seriesLoading, setSeriesLoading] = useState(false);
  const sequence = useRef(0);
  const seriesSequence = useRef(0);
  useEffect(() => {
    setData(undefined); setSeries(undefined); setMarket(''); setTab('facts'); setError('');
    if (!sku) return;
    const controller = new AbortController(); const id = ++sequence.current; setLoading(true);
    api.operationsDetail(sku, controller.signal).then(result => {
      if (controller.signal.aborted || id !== sequence.current) return;
      setData(result);
      const matching = result.markets.find(row => row.asin === initialAsin && row.country === initialCountry) || result.markets[0];
      setMarket(matching ? JSON.stringify([matching.asin, matching.country]) : '');
    }).catch(reason => { if (!controller.signal.aborted && id === sequence.current) setError(reason instanceof Error ? reason.message : 'SKU详情加载失败'); })
      .finally(() => { if (!controller.signal.aborted && id === sequence.current) setLoading(false); });
    return () => { controller.abort(); sequence.current += 1; };
  }, [sku, initialAsin, initialCountry, refreshVersion, retry]);
  useEffect(() => {
    setSeries(undefined); setSeriesError('');
    if (!sku || !market || tab !== 'history') return;
    const [asin, country] = JSON.parse(market) as [string, string];
    const controller = new AbortController(); const id = ++seriesSequence.current; setSeriesLoading(true);
    api.operationsSeries(sku, { asin, country, days }, controller.signal).then(result => { if (!controller.signal.aborted && id === seriesSequence.current) setSeries(result); })
      .catch(reason => { if (!controller.signal.aborted && id === seriesSequence.current) setSeriesError(reason instanceof Error ? reason.message : '趋势加载失败'); })
      .finally(() => { if (!controller.signal.aborted && id === seriesSequence.current) setSeriesLoading(false); });
    return () => { controller.abort(); seriesSequence.current += 1; };
  }, [sku, market, days, tab, refreshVersion, retry]);
  const identity = data?.identity;
  return <Drawer open={sku !== null} onClose={onClose} width="min(900px, 94vw)" title="SKU经营详情" className="ops-details" destroyOnClose>
    {loading && <PageLoading label="正在关联SKU经营证据…" compact />}
    {error && <SectionError title="SKU详情加载失败" error={error} onRetry={() => setRetry(value => value + 1)} />}
    {data && identity && <>
      <div className="ops-detail-identity"><SkuImagePreview image={identity.image} alt={identity.product_name || identity.sku} className="ops-sku-image" placeholderClassName="ops-sku-image-placeholder" width={64} height={64} /><div><h2>{identity.product_name || identity.sku}</h2><Typography.Text copyable>{identity.sku}</Typography.Text><div className="ops-detail-meta">开发员：{identity.developer || '未关联'} · ASIN：{identity.asins.join('、') || '未关联'}</div><RiskTags row={identity} /></div></div>
      <SourceDates sources={data.sources} />
      <Tabs activeKey={tab} onChange={setTab} items={[{ key: 'facts', label: '库存与各国经营', children: <>
        <div className="ops-detail-stats"><div><span>可售库存</span><strong>{quantity(identity.stock)}<small> 件</small></strong></div><div><span>90天以上占用资金</span><strong>{money(identity.capital_90)}</strong></div><div><span>90天销量 / 开售天数</span><strong>{quantity(identity.units_90)} / {quantity(identity.launch_days)}</strong></div></div>
        <h3>SKU汇总销量参考</h3><Descriptions size="small" column={3} items={[{ key: 'units7', label: '7天销量', children: quantity(identity.units_7) + ' 单' }, { key: 'units30', label: '30天销量', children: quantity(identity.units_30) + ' 单' }, { key: 'trend', label: '汇总参考T', children: quantity(identity.units_7 == null || identity.units_30 == null ? null : identity.units_7 / 7 - identity.units_30 / 30, 2) }]} /><p className="ops-secondary">来源：运营原始表，上传快照 {data.sources.operational_sales?.uploaded_at || '未知'}。为SKU跨国汇总，保留原表7／30天口径，不计入站点T排名，也不拆分为每日历史。</p>
        <h3>库存资金</h3><Table size="small" rowKey="label" pagination={false} dataSource={data.aging} columns={[{ title: '库龄', dataIndex: 'label' }, { title: '库存（件）', dataIndex: 'stock', align: 'right', render: value => quantity(value) }, { title: '占用资金', dataIndex: 'capital', align: 'right', render: value => money(value) }]} />
        <div className="ops-detail-discard"><span>弃置测算库龄（独立参数）</span><Segmented aria-label="弃置测算库龄" value={discardScope} onChange={value => setDiscardScope(String(value))} options={['90', '180', '365'].map(value => ({ value, label: `${value}天以上` }))} /></div>
        <Descriptions size="small" column={2} className="ops-detail-reference" items={[{ key: 'provision', label: '全部库存计提参考', children: money(data.provision) }, { key: 'discard', label: '弃置参考', children: money(data.discard_reference?.[discardScope]) }]} />
        <Typography.Paragraph type="secondary">弃置参考沿用原公式及停止店铺排除规则，不改变诊断筛选。金额单位为人民币万元；站点实际价格使用原币种。</Typography.Paragraph>
        <h3>各国经营</h3><Table size="small" rowKey={row => JSON.stringify([row.asin, row.country])} pagination={false} scroll={{ x: 850 }} dataSource={data.markets} columns={[
          { title: 'ASIN / 国家', width: 170, render: (_, row) => <><b>{row.country}</b>{row.historical_only && <span className="ops-secondary"> · 仅历史观察</span>}<div className="ops-secondary">{row.asin}</div></> },
          { title: '实际价', width: 100, render: (_, row) => <>{quantity(row.current_price, 2)}<div className="ops-secondary">{row.currency || '币种缺失'}</div></> },
          { title: '毛利率', width: 95, render: (_, row) => <>{rate(row.margin)}<div className="ops-secondary">{row.units == null ? '销量缺失' : row.units < 5 ? '小样本' : quantity(row.units) + ' 单'}</div></> },
          { title: '销售额 / 毛利润', width: 155, render: (_, row) => <>{money(row.sales)}<div className="ops-secondary">{money(row.profit)}</div></> },
          { title: '广告费占比', width: 100, dataIndex: 'ad_ratio', render: value => rate(value) },
          { title: '评分 / 评价数', width: 115, render: (_, row) => <>{quantity(row.rating, 1)} / {quantity(row.rating_count)}</> },
        ]} />
        <p className="ops-secondary">毛利、销量、广告占比来自毛利源同一周期；实际价和评分来自 {data.sources.listing?.end || '尚未上传'} 的领星快照。缺失证据显示“—”。</p>
      </> }, { key: 'history', label: '趋势与历史', children: <>
        <div className="ops-detail-trend-controls"><Select aria-label="趋势ASIN与国家" value={market || undefined} onChange={setMarket} options={data.markets.map(row => ({ value: JSON.stringify([row.asin, row.country]), label: `${row.country} · ${row.asin}` }))} placeholder="选择ASIN与国家" /><Segmented value={days} onChange={value => setDays(Number(value))} options={[30, 90, 180].map(value => ({ value, label: `${value}天` }))} /></div>
        {!market && <SectionEmpty description="当前SKU暂无可关联的站点身份" />}
        {seriesLoading && <PageLoading label="正在读取销量与实际价格历史…" compact />}
        {seriesError && <SectionError title="趋势加载失败" error={seriesError} onRetry={() => setRetry(value => value + 1)} />}
        {series && <><p className="ops-secondary">{series.rows[0]?.date}～{series.rows[series.rows.length - 1]?.date} · 已观察 {series.rows.filter(row => row.units != null).length} 天销量、{series.rows.filter(row => row.price != null).length} 天价格</p><ObservationChart rows={series.rows} field="units" title="每日销量" /><ObservationChart rows={series.rows} field="price" title="实际价格" /><Alert type="info" showIcon message={`销量截至 ${series.sales_as_of}。缺失日期断线；虚线为实际观察到的变价日，不能据此判断因果。`} />
          <h3>实际变价记录</h3><Table size="small" rowKey={row => JSON.stringify([row.sku, row.asin, row.country, row.date])} pagination={{ pageSize: 6, size: 'small' }} dataSource={series.events} columns={[{ title: '观察日期', dataIndex: 'date' }, { title: '前 → 后实际价', render: (_, row) => `${quantity(row.old_effective_price, 2)} → ${quantity(row.new_effective_price, 2)} ${row.currency}` }, { title: '涨跌幅', dataIndex: 'change', render: value => rate(value) }, { title: '观察说明', dataIndex: 'observation', ellipsis: true }]} />
        </>}
        <h3>人工调价 / 促销登记</h3><Table<Record<string, unknown>> size="small" rowKey={row => `${row.kind}:${row.id ?? row.sku}:${row.created_at ?? row.updated_at ?? ''}`} pagination={{ pageSize: 6, size: 'small' }} dataSource={data.records} expandable={{ expandedRowRender: row => <Descriptions size="small" column={1} items={Object.entries(recordLabels).filter(([key]) => key in row).map(([key, label]) => ({ key, label, children: row[key] == null && key === 'end_date' ? '未设结束日期' : String(row[key] ?? '—') }))} /> }} columns={[{ title: '类型', dataIndex: 'kind', render: value => String(value) }, { title: '生效 / 开始日期', render: (_, row) => String(row.effective_date ?? row.start_date ?? '—') }, { title: '名称 / 原因', render: (_, row) => String(row.promotion_name ?? row.batch_name ?? row.reason ?? '—') }, { title: '登记降幅', render: (_, row) => row.discount_percent == null ? '—' : `${row.discount_percent}%` }, { title: '备注', render: (_, row) => row.voided_at ? '已作废' : row.end_date ? `截止 ${row.end_date}` : row.kind === '长期调价' ? '长期登记' : '未设结束' }]} />
      </> }]} />
    </>}
  </Drawer>;
}
