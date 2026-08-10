import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Card, Empty, Input, Modal, Pagination, Select, Space, Spin, Statistic, Tag, Tooltip, Typography, message } from 'antd';
import { DownOutlined, DownloadOutlined, ReloadOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import {
  api,
  type DashboardPayload,
  type DashboardSection,
  type ReplenishmentCountryMetric,
  type ReplenishmentGroupDetails,
  type ReplenishmentGroupRow,
  type ReplenishmentTag,
} from './api';

const COUNTRY_ORDER = ['DE', 'FR', 'ES', 'IT'] as const;
const COUNTRY_NAMES: Record<typeof COUNTRY_ORDER[number], string> = {
  DE: '德国',
  FR: '法国',
  ES: '西班牙',
  IT: '意大利',
};
const SORT_OPTIONS = [
  { value: '建议补货数量:desc', label: '建议补货数量：高到低' },
  { value: 'ASIN总库存:desc', label: '总库存：高到低' },
  { value: '校准日销量:desc', label: '校准日销量：高到低' },
  { value: 'T值:desc', label: 'T值：高到低' },
  { value: '德国毛利率:desc', label: 'DE毛利率：高到低' },
  { value: '法国毛利率:desc', label: 'FR毛利率：高到低' },
  { value: '西班牙毛利率:desc', label: 'ES毛利率：高到低' },
  { value: '意大利毛利率:desc', label: 'IT毛利率：高到低' },
] as const;
const TAG_PALETTE = ['#2563eb', '#7c3aed', '#0891b2', '#059669', '#d97706', '#dc2626', '#db2777'];
const MIN_QTY_OPTIONS = [
  { value: 0, label: '全部' },
  { value: 10, label: '≥10' },
  { value: 20, label: '≥20' },
  { value: 30, label: '≥30' },
  { value: 50, label: '≥50' },
  { value: 100, label: '≥100' },
  { value: 200, label: '≥200' },
];

type Row = Record<string, unknown>;

function display(value: unknown, precision = 2) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString('zh-CN')
      : value.toLocaleString('zh-CN', { maximumFractionDigits: precision });
  }
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}T/.test(text) ? text.slice(0, 10) : text;
}

function percent(value: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function marginClass(value: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'margin-missing';
  if (value < 0) return 'margin-negative';
  if (value < 0.1) return 'margin-low';
  if (value < 0.2) return 'margin-warning';
  return 'margin-healthy';
}

function trendClass(value: number | null) {
  if (value === null || value === undefined || Number(value) === 0) return 'trend-neutral';
  return Number(value) > 0 ? 'trend-positive' : 'trend-negative';
}

export function maxWeightClass(value: number | null) {
  return value !== null && value !== undefined && Number.isFinite(Number(value)) && Number(value) >= 100
    ? 'weight-warning'
    : '';
}

function ratingClass(score: number | null, reviewCount: number | null = null) {
  if (reviewCount !== null && Number(reviewCount) === 0) return 'rating-missing';
  if (score === null || score === undefined || Number.isNaN(Number(score))) return 'rating-missing';
  if (Number(score) >= 4.3) return 'rating-healthy';
  if (Number(score) >= 3.5) return 'rating-warning';
  return 'rating-danger';
}

function stableTagColor(label: string) {
  let hash = 0;
  for (const char of label) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return TAG_PALETTE[hash % TAG_PALETTE.length];
}

function tagTextColor(color: string) {
  const value = color.replace('#', '');
  if (!/^[0-9a-f]{6}$/i.test(value)) return '#fff';
  const [red, green, blue] = [0, 2, 4].map(index => Number.parseInt(value.slice(index, index + 2), 16));
  return (red * 299 + green * 587 + blue * 114) / 1000 > 155 ? '#111827' : '#fff';
}

function ProductTags({ tags, limit }: { tags: ReplenishmentTag[]; limit?: number }) {
  const visible = typeof limit === 'number' ? tags.slice(0, limit) : tags;
  return <div className="replenishment-tags">
    {visible.map(tag => {
      const color = tag.color || stableTagColor(tag.label);
      return <span key={`${tag.label}-${color}`} style={{ backgroundColor: color, color: tagTextColor(color) }}>{tag.label}</span>;
    })}
    {typeof limit === 'number' && tags.length > limit && <span className="replenishment-tag-more">+{tags.length - limit}</span>}
  </div>;
}

function CompactText({ values, limit = 1, empty = '—' }: { values: string[]; limit?: number; empty?: string }) {
  if (!values.length) return <span className="replenishment-empty">{empty}</span>;
  const text = values.join('；');
  const visible = values.slice(0, limit).join('；');
  return <Tooltip title={text}><span className="replenishment-clamp">{visible}{values.length > limit ? `；+${values.length - limit}` : ''}</span></Tooltip>;
}

function MetricLine({ label, value, className = '' }: { label: string; value: unknown; className?: string }) {
  return <div className={`replenishment-metric-line ${className}`}>
    <span>{label}</span><strong>{display(value)}</strong>
  </div>;
}

function CountryCell({ code, metric }: { code: string; metric: ReplenishmentCountryMetric }) {
  const reasonText = metric.reasons.join('；');
  return <div className="replenishment-country-cell" data-section={code} role="gridcell">
    <div className="replenishment-country-main">
      <span>单量 <strong>{display(metric.units)}</strong></span>
      <span className={`replenishment-margin ${marginClass(metric.margin)}`}>{percent(metric.margin)}</span>
    </div>
    {metric.reasons.length
      ? <Tooltip title={reasonText}><div className="replenishment-reasons">{metric.reasons.slice(0, 2).map((reason, index) => <span key={`${reason}-${index}`}>{reason}</span>)}</div></Tooltip>
      : <span className="replenishment-country-ok">无异常</span>}
  </div>;
}

export function DecisionBoardHeader() {
  return <div className="replenishment-board-grid replenishment-board-header" role="row">
    {['产品识别', 'DE', 'FR', 'ES', 'IT', '库存矩阵', '趋势测算', '销量画像', '补货决策'].map(label => (
      <div key={label} role="columnheader">{label}</div>
    ))}
  </div>;
}

export function SkuDetailPanel({
  details,
  loading,
  error,
  onRetry,
}: {
  details?: ReplenishmentGroupDetails;
  loading: boolean;
  error?: string;
  onRetry: () => void;
}) {
  if (loading) return <div className="replenishment-detail-state"><Spin size="small" /> 正在读取SKU计算明细…</div>;
  if (error) return <Alert type="error" showIcon message="SKU明细读取失败" description={error} action={<Button size="small" onClick={onRetry}>重试</Button>} />;
  if (!details) return null;
  const groupTags = String(details.group['产品标签'] || '').split('；').filter(Boolean);
  const groupColors = String(details.group['产品标签颜色'] || '').split('；');
  const tags = groupTags.map((label, index) => ({ label, color: groupColors[index] || '' }));
  const stockComponents = ['可售', '待调仓', '调仓中', '待入库', '采购在途', '本地库存', '在途', '计划入库'];
  return <div className="replenishment-detail-panel">
    <div className="replenishment-detail-heading">
      <strong>SKU计算明细</strong>
      <ProductTags tags={tags} />
    </div>
    <div className="replenishment-sku-list">
      {details.sku_rows.length ? details.sku_rows.map(row => (
        <article className="replenishment-sku-card" key={`${String(row.MSKU)}-${String(row['补货组ID'])}`}>
          <header>
            <div><Tag color={row['SKU角色'] === '原SKU' ? 'blue' : 'default'}>{display(row['SKU角色'])}</Tag><strong>{display(row.MSKU)}</strong></div>
            <span>{display(row['店铺状态'] || row['店铺名称'])}</span>
            {row['数据异常'] ? <Tag color="error">{display(row['数据异常'])}</Tag> : <Tag color="success">数据正常</Tag>}
          </header>
          <div className="replenishment-sku-sections">
            <section><h4>销量趋势</h4>
              <MetricLine label="7天" value={row['7天销量']} />
              <MetricLine label="14天" value={row['14天销量']} />
              <MetricLine label="30天" value={row['30天销量']} />
              <MetricLine label="T值" value={row['T值']} className={trendClass(Number(row['T值']))} />
              <MetricLine label="校准日销" value={row['校准日销量']} />
            </section>
            <section><h4>库存结构</h4>
              <MetricLine label="亚马逊可售" value={row['SKU亚马逊可售']} />
              <MetricLine label="SKU总库存" value={row['SKU总库存']} />
              <div className="replenishment-stock-components">
                {stockComponents.map(key => <span key={key}><small>{key}</small><strong>{display(row[key])}</strong></span>)}
              </div>
            </section>
            <section><h4>商品与促销</h4>
              <MetricLine label="上架日期" value={row['上架时间']} />
              <MetricLine label="上架天数" value={row['上架天数']} />
              <MetricLine label="单品重量" value={`${display(row['单品重量(g)'])}g`} />
              <MetricLine label="库龄90+" value={row['库龄90天以上']} />
              <MetricLine label="促销开始" value={row['最近促销开始日期']} />
              <MetricLine label="促销截止" value={row['最近促销截止日期']} />
              <MetricLine label="促销折扣" value={row['最近促销折扣'] === null || row['最近促销折扣'] === undefined ? null : `${display(row['最近促销折扣'])}%`} />
            </section>
            <section className="replenishment-sku-margin-section"><h4>分站点毛利率</h4>
              <div className="replenishment-sku-margin-grid">
                {COUNTRY_ORDER.map(code => {
                  const rawMargin = row[`${COUNTRY_NAMES[code]}毛利率`];
                  const margin = rawMargin === null || rawMargin === undefined || rawMargin === ''
                    ? null
                    : Number(rawMargin);
                  const safeMargin = margin !== null && Number.isFinite(margin) ? margin : null;
                  return <span className={`replenishment-sku-margin-cell ${marginClass(safeMargin)}`} key={code}>
                    <small>{code}</small>
                    <strong>{percent(safeMargin)}</strong>
                  </span>;
                })}
              </div>
            </section>
          </div>
        </article>
      )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无SKU明细" />}
    </div>
    {details.sales_history?.available
      ? <section className="replenishment-history-detail">
        <h4>{details.sales_history.title || '销量画像'}</h4>
        <div className="replenishment-history-sites">
          {COUNTRY_ORDER.map(code => <span key={code}><small>{code}</small><strong>{display(details.sales_history!.site_sales[code])}</strong></span>)}
        </div>
        <div className="replenishment-history-months">
          {(details.sales_history.months || []).map(item => (
            <span key={item.month}>
              <small>{item.month}</small>
              <strong>{display(item.total_sales)}</strong>
              <em>计入{item.included_days}天 · {Number(item.adjusted_daily_average).toFixed(2)}/日</em>
            </span>
          ))}
        </div>
      </section>
      : <div className="replenishment-history-empty">往月销量原始表未上传或该ASIN暂无四站销量，不影响建议补货数量。</div>}
  </div>;
}

export function DecisionBoardRow({
  row,
  expanded,
  details,
  detailLoading,
  detailError,
  onToggle,
  onRetry,
  onDisable,
  switchSaving,
}: {
  row: ReplenishmentGroupRow;
  expanded: boolean;
  details?: ReplenishmentGroupDetails;
  detailLoading: boolean;
  detailError?: string;
  onToggle: () => void;
  onRetry: () => void;
  onDisable: (row: ReplenishmentGroupRow) => void;
  switchSaving: boolean;
}) {
  const recommendation = row.recommendation;
  const officialPositive = Number(recommendation.official_quantity || 0) > 0;
  const suggestionClass = recommendation.status === '数据异常'
    ? 'recommendation-error'
    : !recommendation.enabled
      ? 'recommendation-disabled'
      : officialPositive
        ? 'recommendation-positive'
        : 'recommendation-neutral';
  return <div className={`replenishment-row-shell ${expanded ? 'is-expanded' : ''}`}>
    <div
      className="replenishment-board-grid replenishment-board-row"
      role="row"
      tabIndex={0}
      aria-expanded={expanded}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onToggle();
        }
      }}
    >
      <div className="replenishment-identity-cell" data-section="产品识别" role="gridcell">
        <button className="replenishment-expand-button" aria-label={`${expanded ? '收起' : '展开'}${row.identity.asin}明细`} onClick={onToggle}>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </button>
        <div className="replenishment-identity-content">
          <div className="replenishment-asin-line">
            <strong>{row.identity.asin || 'ASIN缺失'}</strong>
            <Select
              aria-label={`${row.identity.asin}补货开关`}
              className="replenishment-row-switch"
              size="small"
              value="enabled"
              loading={switchSaving}
              disabled={switchSaving}
              onKeyDown={event => event.stopPropagation()}
              onChange={value => { if (value === 'disabled') onDisable(row); }}
              options={[
                { value: 'enabled', label: '补货中' },
                { value: 'disabled', label: '不补货' },
              ]}
            />
          </div>
          <div className="replenishment-sku-summary">
            <span>原</span><Tooltip title={row.identity.original_sku}>{row.identity.original_sku || '—'}</Tooltip>
            <span>跟</span><CompactText values={row.identity.follower_skus} limit={2} />
          </div>
          <div className="replenishment-meta-line">
            <CompactText values={row.identity.store_statuses.length ? row.identity.store_statuses : row.identity.stores} limit={2} />
            <i>·</i><CompactText values={row.identity.developers} limit={1} />
            <ProductTags tags={row.identity.tags} limit={2} />
          </div>
          <div className="replenishment-identity-footer">
            <div className="replenishment-identity-promotion">
              {row.promotion
                ? <>
                  <Tooltip title={`${display(row.promotion.start_date)}–${row.promotion.end_date ? display(row.promotion.end_date) : '长期'}`}>
                    <span>{display(row.promotion.start_date)}–{row.promotion.end_date ? display(row.promotion.end_date) : '长期'}</span>
                  </Tooltip>
                  {row.promotion.discount_percent !== null && <b>-{display(row.promotion.discount_percent)}%</b>}
                </>
                : <span className="replenishment-empty">暂无促销</span>}
            </div>
            <span className={`replenishment-rating-badge ${ratingClass(row.identity.rating?.score ?? null, row.identity.rating?.review_count ?? null)}`}>
              {row.identity.rating
                ? `${display(row.identity.rating.review_count)}（${display(row.identity.rating.score)}）`
                : '暂无Rating'}
            </span>
          </div>
        </div>
      </div>
      {COUNTRY_ORDER.map(code => <CountryCell key={code} code={code} metric={row.countries[code]} />)}
      <div className="replenishment-inventory-cell" data-section="库存矩阵" role="gridcell">
        <MetricLine label="亚马逊" value={row.inventory.amazon_available} />
        <MetricLine label="总可售" value={row.inventory.group_total} />
        <MetricLine label={row.inventory.is_split_reference ? 'ASIN参考*' : '跟卖汇总'} value={row.inventory.asin_reference_total} />
        <div className="replenishment-aging-line">
          <span className={Number(row.inventory.aged_over_90 || 0) > 0 ? 'aging-warning' : ''}>90+ {display(row.inventory.aged_over_90)}</span>
          <span className={Number(row.inventory.aged_180_to_365 || 0) > 0 ? 'aging-danger' : ''}>180–365 {display(row.inventory.aged_180_to_365)}</span>
          <span className={Number(row.inventory.aged_over_365 || 0) > 0 ? 'aging-critical' : ''}>365+ {display(row.inventory.aged_over_365)}</span>
        </div>
      </div>
      <div className="replenishment-trend-cell" data-section="趋势测算" role="gridcell">
        <MetricLine label="T值" value={row.trend.t_value} className={trendClass(row.trend.t_value)} />
        <MetricLine label="校准日销" value={row.trend.calibrated_daily_sales} />
        <MetricLine
          label="最大重量"
          value={row.trend.max_weight_g === null ? null : `${display(row.trend.max_weight_g)}g`}
          className={maxWeightClass(row.trend.max_weight_g)}
        />
        <MetricLine label="覆盖天数" value={row.trend.coverage_days === null ? null : `${display(row.trend.coverage_days)}天`} />
      </div>
      <div className="replenishment-history-cell" data-section="销量画像" role="gridcell">
        {row.history.available
          ? <>
            <div className="replenishment-history-site-line">
              {COUNTRY_ORDER.map(code => <span key={code}>{code}(<strong>{display(row.history.site_sales[code])}</strong>)</span>)}
            </div>
            <div className="replenishment-history-peak-grid">
              {row.history.peak_months.map(item => (
                <span key={item.month}>
                  <b>{item.month}：</b>{Number(item.adjusted_daily_average).toFixed(2)} <em>({display(item.total_sales)})</em>
                </span>
              ))}
            </div>
          </>
          : <span className="replenishment-empty">暂无往月销量</span>}
      </div>
      <div className={`replenishment-recommendation-cell ${suggestionClass}`} data-section="补货决策" role="gridcell">
        <MetricLine label="目标库存" value={recommendation.target_inventory} />
        <MetricLine label="测算建议" value={recommendation.measured_quantity} />
        <div className="replenishment-official-quantity"><small>建议补货数量</small><strong>{display(recommendation.official_quantity)}</strong></div>
        <Tooltip title={recommendation.errors.join('；') || recommendation.close_reason || recommendation.status || ''}>
          <span className="replenishment-status-text">{recommendation.status || '—'}</span>
        </Tooltip>
      </div>
    </div>
    {expanded && <SkuDetailPanel details={details} loading={detailLoading} error={detailError} onRetry={onRetry} />}
  </div>;
}

export function ReplenishmentDecisionBoard({
  rows,
  expanded,
  details,
  detailLoading,
  detailErrors,
  onToggle,
  onRetry,
  onDisable,
  switchSavingAsin,
}: {
  rows: ReplenishmentGroupRow[];
  expanded: Set<string>;
  details: Record<string, ReplenishmentGroupDetails | undefined>;
  detailLoading: Set<string>;
  detailErrors: Record<string, string | undefined>;
  onToggle: (groupId: string) => void;
  onRetry: (groupId: string) => void;
  onDisable: (row: ReplenishmentGroupRow) => void;
  switchSavingAsin?: string;
}) {
  return <div className="replenishment-board" role="grid" aria-label="ASIN补货运营决策矩阵" aria-colcount={9}>
    <DecisionBoardHeader />
    <div className="replenishment-board-body">
      {rows.map(row => <DecisionBoardRow
        key={row.group_id}
        row={row}
        expanded={expanded.has(row.group_id)}
        details={details[row.group_id]}
        detailLoading={detailLoading.has(row.group_id)}
        detailError={detailErrors[row.group_id]}
        onToggle={() => onToggle(row.group_id)}
        onRetry={() => onRetry(row.group_id)}
        onDisable={onDisable}
        switchSaving={switchSavingAsin === row.identity.asin}
      />)}
    </div>
  </div>;
}

export default function ReplenishmentPage({ active = true, routeVersion = 0, refreshVersion = 0 }: { active?: boolean; routeVersion?: number; refreshVersion?: number }) {
  const [payload, setPayload] = useState<DashboardPayload>();
  const [section, setSection] = useState<DashboardSection>();
  const [loading, setLoading] = useState(true);
  const [queryLoading, setQueryLoading] = useState(false);
  const [error, setError] = useState('');
  const [developers, setDevelopers] = useState<string[]>([]);
  const [developerSearch, setDeveloperSearch] = useState('');
  const [minQty, setMinQty] = useState(30);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [sort, setSort] = useState('建议补货数量:desc');
  const [details, setDetails] = useState<Record<string, ReplenishmentGroupDetails | undefined>>({});
  const [detailLoading, setDetailLoading] = useState<Set<string>>(new Set());
  const [detailErrors, setDetailErrors] = useState<Record<string, string | undefined>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [switchTarget, setSwitchTarget] = useState<ReplenishmentGroupRow>();
  const [switchReason, setSwitchReason] = useState('');
  const [switchSavingAsin, setSwitchSavingAsin] = useState('');
  const requestId = useRef(0);

  const replenishmentParams = useCallback(
    (): Record<string, string> => ({
      ...(developers.length ? { developers: developers.join(',') } : {}),
      min_qty: String(minQty),
    }),
    [developers, minQty],
  );

  const load = useCallback(async () => {
    const current = ++requestId.current;
    setLoading(true);
    setError('');
    setDetails({});
    setExpanded(new Set());
    try {
      const next = await api.dashboard('replenishment', replenishmentParams());
      if (current !== requestId.current) return;
      setPayload(next);
      setSection(next.sections.find(item => item.key === 'detail'));
      setSearch('');
      setAppliedSearch('');
      setSort('建议补货数量:desc');
    } catch (loadError) {
      if (current === requestId.current) setError(loadError instanceof Error ? loadError.message : '读取补货管理失败');
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, [replenishmentParams]);

  useEffect(() => { if (active) void load(); }, [active, load, routeVersion, refreshVersion]);

  const loadSection = useCallback(async ({
    page = 1,
    pageSize = section?.page_size || 50,
    nextSearch = appliedSearch,
    nextSort = sort,
  }: {
    page?: number;
    pageSize?: number;
    nextSearch?: string;
    nextSort?: string;
  } = {}) => {
    const [sortBy, sortOrder] = nextSort.split(':');
    setQueryLoading(true);
    setError('');
    try {
      const next = await api.dashboardSection('replenishment', 'detail', {
        ...replenishmentParams(),
        page: String(page),
        page_size: String(pageSize),
        ...(nextSearch.trim() ? { search: nextSearch.trim() } : {}),
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setSection(next);
      setAppliedSearch(nextSearch.trim());
      setExpanded(new Set());
    } catch (pageError) {
      setError(pageError instanceof Error ? pageError.message : '读取补货分页失败');
    } finally {
      setQueryLoading(false);
    }
  }, [appliedSearch, replenishmentParams, section?.page_size, sort]);

  const loadDetails = useCallback(async (groupId: string) => {
    setDetailLoading(current => new Set(current).add(groupId));
    setDetailErrors(current => ({ ...current, [groupId]: undefined }));
    try {
      const result = await api.replenishmentGroupDetails(groupId);
      setDetails(current => ({ ...current, [groupId]: result }));
    } catch (detailError) {
      setDetailErrors(current => ({ ...current, [groupId]: detailError instanceof Error ? detailError.message : '读取SKU明细失败' }));
    } finally {
      setDetailLoading(current => {
        const next = new Set(current);
        next.delete(groupId);
        return next;
      });
    }
  }, []);

  const toggle = (groupId: string) => {
    const willExpand = !expanded.has(groupId);
    setExpanded(current => {
      const next = new Set(current);
      if (willExpand) next.add(groupId);
      else next.delete(groupId);
      return next;
    });
    if (willExpand && !details[groupId] && !detailLoading.has(groupId)) void loadDetails(groupId);
  };

  const confirmDisable = async () => {
    if (!switchTarget || !switchReason.trim() || switchSavingAsin) return;
    const asin = switchTarget.identity.asin;
    const groupId = switchTarget.group_id;
    const officialQuantity = Math.max(0, Number(switchTarget.recommendation.official_quantity) || 0);
    const removesPositive = officialQuantity > 0;
    const removesAbnormal = switchTarget.recommendation.status === '数据异常';
    const currentPage = section?.page || 1;
    const pageSize = section?.page_size || 50;
    const visibleRowCount = (section?.group_rows || []).length;
    const shouldLoadPreviousPage = visibleRowCount <= 1 && currentPage > 1;
    setSwitchSavingAsin(asin);
    setError('');
    try {
      await api.updateReplenishmentSwitch(asin, false, switchReason.trim());
      setPayload(current => {
        if (!current) return current;
        const metrics = current.metrics.map(item => {
          const value = Number(item.value) || 0;
          if (item.name === '需补货ASIN数' && removesPositive) return { ...item, value: Math.max(0, value - 1) };
          if (item.name === '建议补货总量' && removesPositive) return { ...item, value: Math.max(0, value - officialQuantity) };
          if (item.name === '数据异常ASIN数' && removesAbnormal) return { ...item, value: Math.max(0, value - 1) };
          return item;
        });
        return { ...current, metrics };
      });
      setSection(current => current ? {
        ...current,
        rows: current.rows.filter(row => String(row.ASIN || '') !== asin),
        group_rows: (current.group_rows || []).filter(row => row.identity.asin !== asin),
        total: Math.max(0, (current.total || 0) - 1),
      } : current);
      setExpanded(current => {
        const next = new Set(current);
        next.delete(switchTarget.group_id);
        return next;
      });
      setDetails(current => {
        const next = { ...current };
        delete next[groupId];
        return next;
      });
      setSwitchTarget(undefined);
      setSwitchReason('');
      message.success(`${asin}已设为不补货并移出矩阵`);
      if (shouldLoadPreviousPage) {
        await loadSection({ page: currentPage - 1, pageSize });
      }
    } catch (switchError) {
      setError(switchError instanceof Error ? switchError.message : '保存补货开关失败');
    } finally {
      setSwitchSavingAsin('');
    }
  };

  const rows = section?.group_rows || payload?.group_rows || [];
  const developerOptions = payload?.filters.developers || [];
  const matchedDevelopers = developerOptions.filter(value => value.toLocaleLowerCase().includes(developerSearch.trim().toLocaleLowerCase()));
  const exportHref = `/api/dashboard/replenishment/export.xlsx?${new URLSearchParams(replenishmentParams()).toString()}`;
  const sortLabel = useMemo(() => SORT_OPTIONS.find(item => item.value === sort)?.label || '建议补货数量：高到低', [sort]);
  return <>
    <div className="page-heading replenishment-page-heading">
      <div><Typography.Title level={2}>补货管理</Typography.Title><Typography.Text type="secondary">ASIN主行汇总所有SKU销量与库存；建议补货数量无需横向滑动即可查看。</Typography.Text></div>
      <Space><Button icon={<DownloadOutlined />} href={exportHref}>导出Excel</Button><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button></Space>
    </div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="补货管理读取失败" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    <Card className="filter-card replenishment-filter-card">
      <Space wrap>
        <Typography.Text strong>开发员</Typography.Text>
        <Select
          aria-label="开发员筛选"
          mode="multiple"
          allowClear
          showSearch
          maxTagCount="responsive"
          placeholder="全部开发员"
          value={developers}
          onChange={setDevelopers}
          onSearch={setDeveloperSearch}
          options={developerOptions.map(value => ({ value, label: value }))}
          dropdownRender={menu => <>
            <Button
              block
              type="text"
              disabled={!matchedDevelopers.length}
              onMouseDown={event => event.preventDefault()}
              onClick={() => setDevelopers(current => Array.from(new Set([...current, ...matchedDevelopers])))}
            >
              全选当前搜索结果（{matchedDevelopers.length}）
            </Button>
            {menu}
          </>}
          style={{ minWidth: 220 }}
        />
        <Typography.Text strong>补货数量</Typography.Text>
        <Select
          aria-label="建议补货数量门槛"
          value={minQty}
          options={MIN_QTY_OPTIONS}
          style={{ width: 105 }}
          onChange={value => setMinQty(value)}
        />
        <Input
          allowClear
          value={search}
          prefix={<SearchOutlined />}
          placeholder="搜索ASIN、SKU、店铺、标签"
          onChange={event => setSearch(event.target.value)}
          onPressEnter={() => void loadSection({ page: 1, nextSearch: search })}
          style={{ width: 250 }}
        />
        <Button onClick={() => void loadSection({ page: 1, nextSearch: search })}>搜索</Button>
        <Typography.Text strong>排序</Typography.Text>
        <Select
          value={sort}
          options={[...SORT_OPTIONS]}
          style={{ width: 205 }}
          onChange={value => {
            setSort(value);
            void loadSection({ page: 1, nextSort: value });
          }}
        />
        {appliedSearch && <Tag closable onClose={() => { setSearch(''); void loadSection({ page: 1, nextSearch: '' }); }}>搜索：{appliedSearch}</Tag>}
      </Space>
    </Card>
    <div className="metric-grid replenishment-metric-grid">{(payload?.metrics || []).map(item => <Card key={item.name}><Statistic title={item.name} value={Number(item.value) || 0} precision={0} /></Card>)}</div>
    <Card className="dashboard-section replenishment-dashboard-card" title="ASIN补货运营决策矩阵" extra={<Typography.Text type="secondary">{sortLabel} · 点击行展开SKU明细</Typography.Text>}>
      <Spin spinning={loading || queryLoading}>
        {rows.length
          ? <ReplenishmentDecisionBoard
            rows={rows}
            expanded={expanded}
            details={details}
            detailLoading={detailLoading}
            detailErrors={detailErrors}
            onToggle={toggle}
            onRetry={groupId => void loadDetails(groupId)}
            onDisable={row => {
              setSwitchTarget(row);
              setSwitchReason('');
            }}
            switchSavingAsin={switchSavingAsin}
          />
          : <Empty description={loading ? '正在计算补货建议…' : payload?.message || '暂无补货数据'} />}
        <div className="replenishment-pagination">
          <Pagination
            current={section?.page || 1}
            pageSize={section?.page_size || 50}
            total={section?.total || rows.length}
            showSizeChanger
            pageSizeOptions={[10, 20, 50, 100]}
            showTotal={total => `共 ${total} 个补货组`}
            onChange={(page, pageSize) => void loadSection({ page, pageSize })}
          />
        </div>
      </Spin>
    </Card>
    <Modal
      title={`设置${switchTarget?.identity.asin || ''}为不补货`}
      open={Boolean(switchTarget)}
      okText="确认不补货"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !switchReason.trim(), loading: Boolean(switchSavingAsin) }}
      cancelButtonProps={{ disabled: Boolean(switchSavingAsin) }}
      closable={!switchSavingAsin}
      maskClosable={!switchSavingAsin}
      onCancel={() => {
        if (!switchSavingAsin) {
          setSwitchTarget(undefined);
          setSwitchReason('');
        }
      }}
      onOk={() => void confirmDisable()}
    >
      <Typography.Paragraph type="secondary">
        保存后该ASIN会立即从补货矩阵和导出中移除，并自动写入配置中心的“补货开关”。
      </Typography.Paragraph>
      <Input.TextArea
        autoFocus
        value={switchReason}
        maxLength={200}
        showCount
        autoSize={{ minRows: 3, maxRows: 5 }}
        placeholder="请输入不补货原因（必填）"
        onChange={event => setSwitchReason(event.target.value)}
      />
    </Modal>
  </>;
}
