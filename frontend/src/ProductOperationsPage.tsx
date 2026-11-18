import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, InputNumber, Space, Table, Tabs, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CopyOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';

import { api, type DiagnosisScene, type OperationsPayload, type OperationsSku } from './api';
import type { PageLifecycleProps } from './pageLifecycle';
import PageHeading from './components/PageHeading';
import { PageLoading, SectionError, SectionEmpty } from './components/PageState';
import SkuDetailsDrawer from './components/SkuDetailsDrawer';
import ConfirmFilterSelect from './ConfirmFilterSelect';
import FilterActions from './FilterActions';
import { copyWithFeedback, downloadBlobWithFeedback, feedbackMessage } from './feedback';
import { AgingBar, money, quantity, rate, RiskTags, SkuIdentity, SourceDates } from './operationsPresentation';
import './ProductOperations.css';

export function diagnosisScene(search: string): DiagnosisScene {
  const params = new URLSearchParams(search);
  if (params.get('page') === 'new-products') return 'new';
  if (params.get('tab') === 'low-margin') return 'margin';
  const value = params.get('scene');
  return value === 'margin' || value === 'new' ? value : 'clearance';
}
type Query = { scene: DiagnosisScene; developers: string; search: string; age_scope: string; margin_bands: string; country: string; min_sales: number; new_mode: string; sales_min?: number; sales_max?: number; sort_by: string; sort_order: 'asc' | 'desc'; page: number; page_size: number };
const initialQuery = (scene: DiagnosisScene): Query => ({ scene, developers: '', search: '', age_scope: '90', margin_bands: 'negative,0-5,5-12,12-20', country: '', min_sales: 0, new_mode: 'low', sort_by: '', sort_order: 'desc', page: 1, page_size: 50 });
const marginOptions = [{ value: 'negative', label: '＜0%' }, { value: '0-5', label: '0%≤毛利＜5%' }, { value: '5-12', label: '5%≤毛利＜12%' }, { value: '12-20', label: '12%≤毛利＜20%' }, { value: '20-plus', label: '≥20%' }, { value: 'missing', label: '毛利缺失' }];

export default function ProductOperationsPage({ active = true, routeVersion = 0, refreshVersion = 0 }: PageLifecycleProps) {
  const [query, setQuery] = useState<Query>(() => ({ ...initialQuery(diagnosisScene(window.location.search)), developers: new URLSearchParams(window.location.search).get('developers') || '', search: new URLSearchParams(window.location.search).get('search') || '' }));
  const [searchDraft, setSearchDraft] = useState(query.search);
  const [data, setData] = useState<OperationsPayload>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [sku, setSku] = useState<string | null>(null);
  const [minDraft, setMinDraft] = useState(0);
  const [salesPreset, setSalesPreset] = useState('default');
  const [salesDraft, setSalesDraft] = useState<[number | null, number | null]>([null, null]);
  const [exporting, setExporting] = useState(false);
  const exportLock = useRef(false);
  const requestId = useRef(0);
  const revision = useRef('');
  const params = useMemo(() => ({ ...query }), [query]);
  const apply = (values: Partial<Query>) => { setSelected([]); setQuery(current => ({ ...current, ...values, page: 1 })); };

  useEffect(() => {
    if (!active) return;
    const next = diagnosisScene(window.location.search);
    if (next !== query.scene) { setData(undefined); setSelected([]); setQuery(current => ({ ...initialQuery(next), developers: current.developers, search: current.search })); setSalesPreset('default'); }
  }, [active, routeVersion, query.scene]);
  useEffect(() => { setSelected([]); }, [refreshVersion]);
  useEffect(() => { if (!active) setSku(null); }, [active]);
  useEffect(() => {
    if (!active || diagnosisScene(window.location.search) !== query.scene) return;
    const controller = new AbortController(); const id = ++requestId.current;
    setLoading(true); setError('');
    api.operations(params, controller.signal).then(result => {
      if (controller.signal.aborted || id !== requestId.current) return;
      const maxPage = Math.max(1, Math.ceil(result.total / query.page_size));
      if (query.page > maxPage) { setQuery(current => ({ ...current, page: maxPage })); return; }
      if (revision.current && revision.current !== result.revision) setSelected([]);
      revision.current = result.revision; setData(result);
    }).catch(reason => { if (!controller.signal.aborted && id === requestId.current) setError(reason instanceof Error ? reason.message : '经营数据加载失败'); })
      .finally(() => { if (!controller.signal.aborted && id === requestId.current) setLoading(false); });
    return () => { controller.abort(); requestId.current += 1; };
  }, [active, params, query.scene, query.page, query.page_size, routeVersion, refreshVersion, retry]);
  useEffect(() => {
    if (!active) return;
    let day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const timer = window.setInterval(() => { const next = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date()); if (next !== day) { day = next; setSelected([]); setRetry(value => value + 1); } }, 60_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const changeScene = (scene: DiagnosisScene) => {
    if (scene === query.scene) return;
    const url = new URL(window.location.href); url.searchParams.set('page', 'product-operations'); url.searchParams.set('scene', scene);
    url.searchParams.delete('tab'); window.history.pushState({}, '', url); window.dispatchEvent(new Event('sales-dashboard-route-change'));
    setData(undefined); setSelected([]); setSku(null); setSalesPreset('default'); setMinDraft(0);
    setQuery(current => ({ ...initialQuery(scene), developers: current.developers, search: current.search }));
  };
  const exportRows = async () => {
    if (exportLock.current) return;
    exportLock.current = true; setExporting(true);
    try { const blob = await api.exportOperations({ ...params, revision: data?.revision }, selected.length ? selected : undefined); await downloadBlobWithFeedback(blob, 'SKU经营处理清单.csv', 'SKU处理清单'); }
    catch (reason) { feedbackMessage.error(reason instanceof Error ? reason.message : '导出失败'); }
    finally { exportLock.current = false; setExporting(false); }
  };
  const columns: ColumnsType<OperationsSku> = [{ title: '产品 / SKU', key: 'identity', width: 270, render: (_, row) => <SkuIdentity row={row} onOpen={() => setSku(row.sku)} /> }];
  if (query.scene === 'clearance') columns.push(
    { title: '占用资金', key: 'scope_capital', dataIndex: 'scope_capital', width: 135, align: 'right', sorter: true, render: money },
    { title: '库龄库存', key: 'scope_stock', width: 160, align: 'right', sorter: true, render: (_, row) => <><b>{quantity(row.scope_stock)}</b><AgingBar row={row} /></> },
    { title: <Tooltip title="同补货校准公式：运营上架不足90天，7/14/30天日均权重为90%/9%/1%；满90天为60%/30%/10%。逐行计算后仅在本SKU内汇总。">日均销量</Tooltip>, key: 'clearance_daily_units', dataIndex: 'clearance_daily_units', width: 110, align: 'right', sorter: true,
      render: value => <Tooltip trigger={['hover', 'focus']} title={value == null ? '缺少有效上架时间或7／14／30天销量，不用部分数据计算' : `补货口径 ${quantity(value, 6)} 单/天；天数使用未四舍五入值计算`}><span tabIndex={0} className="ops-numeric">{value != null && value > 0 && value < .01 ? '＜0.01' : quantity(value, 2)}</span></Tooltip> },
    { title: <Tooltip title="本SKU全部库龄、含停提款店铺的补货总库存÷校准日均。总库存含可售、待调仓、调仓中、待入库×2、采购在途、本地、在途、计划入库。">可售天数</Tooltip>, key: 'clearance_available_days', width: 120, align: 'right', sorter: true,
      render: (_, row) => <Tooltip trigger={['hover', 'focus']} title={`补货口径总库存 ${quantity(row.clearance_total_stock)} 件 ÷ 校准日均 ${quantity(row.clearance_daily_units, 6)} 单/天。缺少库存组成或日均不大于0时不计算；库龄筛选不改变本SKU分子。`}><span tabIndex={0} className="ops-numeric">{row.clearance_available_days == null ? '—' : quantity(row.clearance_available_days, 2) + '天'}</span></Tooltip> },
    { title: '90天销量', key: 'units_90', dataIndex: 'units_90', width: 110, align: 'right', sorter: true, render: value => quantity(value) },
    { title: '利润与新品', key: 'risks', width: 215, render: (_, row) => <><RiskTags row={row} /><span className="ops-secondary">最差站点毛利 {rate(row.worst_margin)}</span></> },
  );
  if (query.scene === 'margin') columns.push(
    { title: '命中站点', key: 'matched_margin', width: 160, sorter: true, render: (_, row) => <><b>{rate(row.matched_margin)}</b><span className="ops-secondary">{row.matched_countries} · {row.matched_markets}条</span></> },
    { title: '销售额 / 毛利润', key: 'matched_profit', width: 180, align: 'right', sorter: true, render: (_, row) => <>{money(row.matched_sales)}<span className="ops-secondary">毛利 {money(row.matched_profit)}</span></> },
    { title: '库存与销量', width: 150, align: 'right', render: (_, row) => <>{quantity(row.stock)}件可售<span className="ops-secondary">{quantity(row.matched_units)}单{row.small_sample_markets ? ` · ${row.small_sample_markets}处小样本` : ''}</span></> },
    { title: '交叉风险', width: 210, render: (_, row) => <><RiskTags row={row} /><span className="ops-secondary">90天以上资金 {money(row.capital_90)}</span></> },
  );
  if (query.scene === 'new') columns.push(
    { title: '开售', key: 'launch_days', width: 140, sorter: true, render: (_, row) => <>{quantity(row.launch_days)}天<span className="ops-secondary">{row.launch_date}{row.launch_days != null && row.launch_days < 7 ? ' · 观察期' : ''}</span></> },
    { title: '90天销量', dataIndex: 'units_90', key: 'units_90', width: 115, align: 'right', sorter: true, render: value => <b>{quantity(value)}{value === 0 ? ' · 零单' : ''}</b> },
    { title: '可售 / 覆盖', width: 145, align: 'right', render: (_, row) => <>{quantity(row.stock)}件<span className="ops-secondary">覆盖 {row.daily_units === 0 && row.stock != null && row.stock > 0 ? '∞' : quantity(row.coverage_days, 1)} 天</span></> },
    { title: '利润与积压', width: 210, render: (_, row) => <><RiskTags row={row} /><span className="ops-secondary">最差站点毛利 {rate(row.worst_margin)}</span></> },
  );
  columns.forEach(column => { if (column.sorter) column.sortOrder = column.key === query.sort_by ? query.sort_order === 'asc' ? 'ascend' : 'descend' : null; });
  const title = query.scene === 'clearance' ? `${query.age_scope}天以上占用资金` : query.scene === 'margin' ? '当前毛利范围SKU' : query.new_mode === 'low' ? '低销量新品' : '开售不足100天新品';
  const headline = query.scene === 'clearance' ? money(data?.summary.scope_capital) : quantity(data?.total);
  return <div className="ops-page ops-diagnosis">
    <PageHeading title="经营诊断" description={<SourceDates sources={data?.sources} />} actions={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRetry(value => value + 1)}>刷新</Button>} />
    <Tabs className="ops-scene-tabs" activeKey={query.scene} onChange={value => changeScene(value as DiagnosisScene)} items={[{ key: 'clearance', label: '积压清仓' }, { key: 'margin', label: '利润风险' }, { key: 'new', label: '新品低销' }]} />
    <div className="ops-filter-bar"><Space wrap>
      <ConfirmFilterSelect mode="multiple" ariaLabel="经营诊断开发员" selectionUnit="人" placeholder="全部开发员" value={query.developers ? query.developers.split(',') : []} options={(data?.developers || []).map(value => ({ value, label: value }))} onConfirm={value => apply({ developers: Array.isArray(value) ? value.join(',') : '' })} style={{ width: 210 }} />
      {query.scene === 'clearance' && <ConfirmFilterSelect mode="single" ariaLabel="清仓库龄范围" placeholder="库龄范围" value={query.age_scope} normalizeValue={value => value || '90'} options={['90', '180', '365'].map(value => ({ value, label: `${value}天以上` }))} onConfirm={value => apply({ age_scope: String(value || '90') })} style={{ width: 150 }} />}
      {query.scene === 'margin' && <>
        <ConfirmFilterSelect mode="multiple" ariaLabel="利润毛利档位" placeholder="全部毛利档位" value={query.margin_bands === 'all' ? [] : query.margin_bands.split(',')} options={marginOptions} onConfirm={value => apply({ margin_bands: Array.isArray(value) && value.length ? value.join(',') : 'all' })} style={{ width: 190 }} />
        <ConfirmFilterSelect mode="single" ariaLabel="利润国家" placeholder="全部国家" value={query.country || undefined} options={['DE', 'FR', 'ES', 'IT'].map(value => ({ value, label: value }))} onConfirm={value => apply({ country: String(value || '') })} style={{ width: 130 }} />
        <InputNumber aria-label="最少站点销量" min={0} precision={0} placeholder="最少单量" value={minDraft} onChange={value => setMinDraft(value ?? 0)} style={{ width: 110 }} /><Button onClick={() => apply({ min_sales: minDraft })}>应用单量</Button>
      </>}
      {query.scene === 'new' && <>
        <ConfirmFilterSelect mode="single" ariaLabel="新品范围" placeholder="新品范围" value={query.new_mode} normalizeValue={value => value || 'low'} options={[{ value: 'low', label: '有库存低销量' }, { value: 'all', label: '全部新品' }]} onConfirm={value => { setSalesPreset('default'); apply({ new_mode: String(value || 'low'), sales_min: undefined, sales_max: undefined }); }} style={{ width: 160 }} />
        <ConfirmFilterSelect mode="single" ariaLabel="新品90天销量" placeholder="90天销量" value={salesPreset} normalizeValue={value => value || 'default'} options={[{ value: 'default', label: query.new_mode === 'low' ? '默认＜5单' : '全部销量' }, { value: '0:1', label: '零单' }, { value: '0:5', label: '＜5单' }, { value: '5:10', label: '5≤销量＜10单' }, { value: '10:20', label: '10≤销量＜20单' }, { value: '20:30', label: '20≤销量＜30单' }, { value: '30:', label: '≥30单' }, { value: '0:', label: '全部已知销量' }, { value: 'custom', label: '自定义' }]}
          onConfirm={value => { const preset = String(value || 'default'); setSalesPreset(preset); if (preset !== 'custom') { const [lower, upper] = preset === 'default' ? [] : preset.split(':'); apply({ sales_min: lower ? Number(lower) : undefined, sales_max: upper ? Number(upper) : undefined }); } }} style={{ width: 185 }} />
        {salesPreset === 'custom' && <Space><InputNumber aria-label="90天销量下限" min={0} precision={0} placeholder="下限（含）" value={salesDraft[0]} onChange={value => setSalesDraft([value, salesDraft[1]])} style={{ width: 120 }} /><InputNumber aria-label="90天销量上限" min={0} precision={0} placeholder="上限（不含）" value={salesDraft[1]} onChange={value => setSalesDraft([salesDraft[0], value])} style={{ width: 120 }} /><Button disabled={salesDraft[0] != null && salesDraft[1] != null && salesDraft[0] >= salesDraft[1]} onClick={() => apply({ sales_min: salesDraft[0] ?? undefined, sales_max: salesDraft[1] ?? undefined })}>应用范围</Button></Space>}
      </>}
      <Input.Search placeholder="搜索品名 / SKU / ASIN" value={searchDraft} allowClear onChange={event => setSearchDraft(event.target.value)} onSearch={value => apply({ search: value.trim() })} style={{ width: 245 }} />
      <FilterActions onReset={() => { setSelected([]); setSearchDraft(''); setMinDraft(0); setSalesPreset('default'); setSalesDraft([null, null]); setQuery(initialQuery(query.scene)); }} />
    </Space></div>
    {error && <SectionError title="经营诊断加载失败" error={error} onRetry={() => setRetry(value => value + 1)} />}
    {!data && loading ? <PageLoading label="正在关联SKU经营证据…" /> : <>
      <section className="ops-hero" aria-label="当前诊断范围"><div><span className="ops-hero-label">{title}</span><div className="ops-hero-number">{headline}</div></div><div className="ops-hero-context">
        <span>当前命中 <b>{quantity(data?.total)}</b> 个SKU</span>
        {query.scene === 'clearance' ? <span>对应库存 <b>{quantity(data?.summary.scope_stock)}</b> 件</span> : query.scene === 'margin' ? <span>{quantity(data?.summary.market_count)}条站点记录 · 毛利润 {money(data?.summary.matched_profit)}</span> : <span>零单 {quantity(data?.summary.zero_sales)}款 · 可售 {quantity(data?.summary.stock)}件</span>}
        <Typography.Text type="secondary">{query.scene === 'clearance' ? '优先处理资金占用最多的SKU；悬停库龄条查看构成。' : query.scene === 'margin' ? '按命中站点最差毛利排序，小样本保留；低毛利不等于应当降价。' : '90天销量来自运营表，不等于开售以来销量。'}</Typography.Text>
      </div></section>
      {query.scene === 'new' && !!data?.missing_launch_count && <Alert type="info" message={`${data.missing_launch_count}个SKU缺少有效开售日期，未纳入新品。`} />}
      {data && !data.sources.gross_profit?.available && <Alert type="info" message="尚未上传毛利原始表，利润证据暂缺；库存和新品诊断可继续使用。" />}
      <section className="ops-box ops-queue"><div className="ops-section-heading"><div><h2>SKU处理队列</h2><span>{selected.length ? `已选 ${selected.length} 个SKU` : '勾选所需SKU，或导出全部匹配结果'}</span></div><Space wrap>
        <Button icon={<CopyOutlined />} disabled={loading || !selected.length} onClick={() => void copyWithFeedback(selected.join('\n'), '所选SKU', selected.length)}>复制所选SKU</Button>
        <Button icon={<DownloadOutlined />} loading={exporting} disabled={loading || !!error || !data?.total} onClick={() => void exportRows()}>{selected.length ? '导出所选清单' : '导出筛选结果'}</Button>
      </Space></div>
      {!data || query.scene !== 'margin' && !data.sources.operational_sales?.available ? <SectionEmpty description="到上传中心上传运营原始表后开始诊断。" /> : <Table<OperationsSku> size="small" tableLayout="fixed" rowKey="sku" loading={loading} dataSource={data.rows} columns={columns} scroll={{ x: query.scene === 'clearance' ? 1160 : 940 }} rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: keys => setSelected(keys.map(String)) }}
        pagination={{ current: query.page, pageSize: query.page_size, total: data.total, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 个SKU` }} onChange={(pagination, _filters, sorter, extra) => {
          if (extra.action === 'sort') { const item = Array.isArray(sorter) ? sorter[0] : sorter; apply({ sort_by: item.order ? String(item.columnKey) : '', sort_order: item.order === 'ascend' ? 'asc' : 'desc' }); }
          else setQuery(current => ({ ...current, page: pagination.pageSize !== current.page_size ? 1 : pagination.current || 1, page_size: pagination.pageSize || 50 }));
        }} />}
      </section>
    </>}
    <SkuDetailsDrawer sku={active ? sku : null} onClose={() => setSku(null)} refreshVersion={refreshVersion} />
  </div>;
}
