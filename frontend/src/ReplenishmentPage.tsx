import { useCallback, useEffect, useId, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { Alert, Button, Card, Empty, Input, Modal, Pagination, Select, Space, Spin, Statistic, Tag, Tooltip, Typography } from 'antd';
import { feedbackMessage as message, downloadWithFeedback } from './feedback';
import { DownOutlined, DownloadOutlined, ReloadOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import {
  api,
  type DashboardPayload,
  type DashboardSection,
  type ReplenishmentCountryMetric,
  type ReplenishmentGroupDetails,
  type ReplenishmentGroupRow,
  type ReplenishmentHistoryMonth,
  type ReplenishmentPriceHistoryPoint,
  type ReplenishmentTag,
} from './api';
import SkuImagePreview from './SkuImagePreview';
import FilterActions from './FilterActions';
import ConfirmFilterSelect from './ConfirmFilterSelect';

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
type ReplenishmentPriceCountry = NonNullable<NonNullable<ReplenishmentGroupRow['pricing']>['countries']['DE']>;
type ReplenishmentPriceChange = NonNullable<ReplenishmentPriceCountry['latest_change']>;

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

function adjustedDailyDisplay(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)}/天` : '—';
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

function compareHistoryMonths(left: ReplenishmentHistoryMonth, right: ReplenishmentHistoryMonth) {
  const parse = (value: unknown) => {
    const text = String(value ?? '');
    const match = text.match(/^(\d{4})-(\d{1,2})$/);
    if (match) return Number(match[1]) * 100 + Number(match[2]);
    const numeric = Number(text);
    return Number.isFinite(numeric) ? numeric : Number.MAX_SAFE_INTEGER;
  };
  return parse(left.month) - parse(right.month) || String(left.month).localeCompare(String(right.month));
}

function normalizedHistoryMonths(months: ReplenishmentHistoryMonth[] | undefined) {
  return [...(months || [])]
    .filter(item => item && String(item.month ?? '').trim())
    .sort(compareHistoryMonths)
    .map(item => ({
      ...item,
      total_sales: Number.isFinite(Number(item.total_sales)) ? Number(item.total_sales) : 0,
      adjusted_daily_average: Number.isFinite(Number(item.adjusted_daily_average)) ? Number(item.adjusted_daily_average) : 0,
      adjusted_average_available: Number.isFinite(Number(item.adjusted_daily_average)),
      included_days: Number.isFinite(Number(item.included_days)) ? Number(item.included_days) : 0,
    }));
}

type ChartPoint = { x: number; y: number };
type ChartTooltipPosition = {
  left: number;
  top: number;
  horizontal: 'left' | 'center' | 'right';
  vertical: 'above' | 'below';
};

function monotonePath(points: ChartPoint[]) {
  if (!points.length) return '';
  if (points.length === 1) return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  if (points.length === 2) {
    return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)} L ${points[1].x.toFixed(2)} ${points[1].y.toFixed(2)}`;
  }
  const intervals = points.slice(1).map((point, index) => point.x - points[index].x);
  const secants = points.slice(1).map((point, index) => {
    const interval = intervals[index] || 1;
    return (point.y - points[index].y) / interval;
  });
  const tangents = new Array(points.length).fill(0) as number[];
  const endpointTangent = (first: number, second: number, interval: number) => {
    const candidate = ((2 * interval + intervals[second]!) * secants[first]! - interval * secants[second]!)
      / (interval + intervals[second]!);
    if (candidate * secants[first]! <= 0) return 0;
    if (secants[first]! * secants[second]! < 0 && Math.abs(candidate) > Math.abs(3 * secants[first]!)) {
      return 3 * secants[first]!;
    }
    return candidate;
  };
  tangents[0] = endpointTangent(0, 1, intervals[0]!);
  tangents[tangents.length - 1] = endpointTangent(secants.length - 1, secants.length - 2, intervals[intervals.length - 1]!);
  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = secants[index - 1]!;
    const next = secants[index]!;
    if (previous * next <= 0) {
      tangents[index] = 0;
      continue;
    }
    const leftWeight = 2 * intervals[index]! + intervals[index - 1]!;
    const rightWeight = intervals[index]! + 2 * intervals[index - 1]!;
    tangents[index] = (leftWeight + rightWeight)
      / (leftWeight / previous + rightWeight / next);
  }
  return points.slice(1).reduce((path, point, index) => {
    const start = points[index]!;
    const interval = intervals[index]!;
    const firstControl = { x: start.x + interval / 3, y: start.y + tangents[index]! * interval / 3 };
    const secondControl = { x: point.x - interval / 3, y: point.y - tangents[index + 1]! * interval / 3 };
    return `${path} C ${firstControl.x.toFixed(2)} ${firstControl.y.toFixed(2)}, ${secondControl.x.toFixed(2)} ${secondControl.y.toFixed(2)}, ${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
  }, `M ${points[0]!.x.toFixed(2)} ${points[0]!.y.toFixed(2)}`);
}

function MonthlySalesTrendChart({
  months,
  compact = false,
}: {
  months?: ReplenishmentHistoryMonth[];
  compact?: boolean;
}) {
  const data = normalizedHistoryMonths(months);
  const chartId = useId();
  const gradientId = useMemo(() => `replenishment-monthly-gradient-${chartId.replace(/[^a-zA-Z0-9_-]/g, '-')}`, [chartId]);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState<ChartTooltipPosition | null>(null);
  const width = compact ? 360 : 960;
  const height = compact ? 86 : 250;
  const padding = compact
    ? { left: 28, right: 28, top: 19, bottom: 15 }
    : { left: 42, right: 42, top: 28, bottom: 39 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const totalMax = Math.max(1, ...data.map(item => item.total_sales));
  const averageMax = Math.max(1, ...data.map(item => item.adjusted_daily_average));
  const x = (index: number) => data.length === 1
    ? padding.left + plotWidth / 2
    : padding.left + index * plotWidth / (data.length - 1);
  const totalY = (value: number) => padding.top + plotHeight - (value / totalMax) * plotHeight;
  const averageY = (value: number) => padding.top + plotHeight - (value / averageMax) * plotHeight;
  const totalPoints = data.map((item, index) => ({ x: x(index), y: totalY(item.total_sales) }));
  const averagePoints = data.map((item, index) => ({ x: x(index), y: averageY(item.adjusted_daily_average) }));
  const totalPath = monotonePath(totalPoints);
  const averagePath = monotonePath(averagePoints);
  const baselineY = padding.top + plotHeight;
  const totalAreaPath = `${totalPath} L ${x(data.length - 1).toFixed(2)} ${baselineY.toFixed(2)} L ${x(0).toFixed(2)} ${baselineY.toFixed(2)} Z`;
  const totalTicks = compact ? [] : [0, .5, 1].map(ratio => ({ ratio, value: totalMax * ratio }));
  const averageTicks = compact ? [] : [0, .5, 1].map(ratio => ({ ratio, value: averageMax * ratio }));
  const clearActivePoint = useCallback(() => {
    setActiveIndex(null);
    setTooltipPosition(null);
  }, []);
  useEffect(() => {
    if (activeIndex !== null && activeIndex >= data.length) clearActivePoint();
  }, [activeIndex, clearActivePoint, data.length]);
  useEffect(() => {
    if (activeIndex === null) return undefined;
    const clearOnViewportChange = () => clearActivePoint();
    window.addEventListener('scroll', clearOnViewportChange, true);
    window.addEventListener('resize', clearOnViewportChange);
    return () => {
      window.removeEventListener('scroll', clearOnViewportChange, true);
      window.removeEventListener('resize', clearOnViewportChange);
    };
  }, [activeIndex, clearActivePoint]);
  const activatePoint = useCallback((event: ReactPointerEvent<SVGRectElement>) => {
    const svg = svgRef.current;
    const rect = svg?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return;
    const localX = (event.clientX - rect.left) * width / rect.width;
    const plotX = Math.max(padding.left, Math.min(width - padding.right, localX));
    const ratio = data.length === 1 ? 0 : (plotX - padding.left) / plotWidth;
    const nextIndex = Math.max(0, Math.min(data.length - 1, Math.round(ratio * (data.length - 1))));
    const point = data[nextIndex]!;
    const screenX = rect.left + x(nextIndex) / width * rect.width;
    const pointY = Math.min(totalY(point.total_sales), averageY(point.adjusted_daily_average));
    const screenY = rect.top + pointY / height * rect.height;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
    const anchoredX = Math.max(8, Math.min(viewportWidth - 8, screenX));
    const anchoredY = Math.max(8, Math.min(window.innerHeight - 8, screenY));
    setActiveIndex(nextIndex);
    setTooltipPosition({
      left: anchoredX,
      top: anchoredY,
      horizontal: anchoredX < 120 ? 'right' : anchoredX > viewportWidth - 120 ? 'left' : 'center',
      vertical: anchoredY > 130 ? 'above' : 'below',
    });
  }, [averageY, data, height, padding.left, padding.right, plotWidth, totalY, width, x]);
  const activePoint = activeIndex === null ? null : data[activeIndex];
  const portalIsDark = typeof document !== 'undefined' && Boolean(document.querySelector('.app-shell.dark-mode'));
  const tooltip = activePoint && tooltipPosition && typeof document !== 'undefined'
    ? createPortal(
      <div
        className={`replenishment-monthly-chart-tooltip ${compact ? 'compact' : 'full'} tooltip-${tooltipPosition.horizontal} tooltip-${tooltipPosition.vertical}${portalIsDark ? ' is-dark' : ''}`}
        role="tooltip"
        aria-live="polite"
        style={{ left: tooltipPosition.left, top: tooltipPosition.top }}
      >
        <strong>{String(activePoint.month)}</strong>
        <div><i className="replenishment-monthly-chart-tooltip-total" />月总销量 <b>{display(activePoint.total_sales)} 件</b></div>
        <div><i className="replenishment-monthly-chart-tooltip-average" />校准日均 <b>{activePoint.adjusted_average_available ? adjustedDailyDisplay(activePoint.adjusted_daily_average) : '—'}</b></div>
        <small>计入 {display(activePoint.included_days)} 天</small>
      </div>,
      document.body,
    )
    : null;
  if (!data.length) return <span className="replenishment-history-group-empty">—</span>;
  return <div className={`replenishment-monthly-chart ${compact ? 'compact' : 'full'}`}>
    <div className="replenishment-monthly-chart-legend" aria-label="销量图例">
      <span><i className="replenishment-monthly-chart-legend-total" />月总销量</span>
      <span><i className="replenishment-monthly-chart-legend-average" />校准日均</span>
    </div>
    <svg
      ref={svgRef}
      className="replenishment-monthly-chart-svg"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="月总销量与校准日均销量趋势"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2563eb" stopOpacity={compact ? 0.18 : 0.2} />
          <stop offset="100%" stopColor="#2563eb" stopOpacity="0" />
        </linearGradient>
      </defs>
      {!compact && <>
        {totalTicks.map(tick => <g key={`total-${tick.ratio}`} className="replenishment-monthly-chart-axis">
          <line className="replenishment-monthly-chart-grid" x1={padding.left} x2={width - padding.right} y1={padding.top + plotHeight * (1 - tick.ratio)} y2={padding.top + plotHeight * (1 - tick.ratio)} />
          <text x={padding.left - 6} y={padding.top + plotHeight * (1 - tick.ratio) + 3} textAnchor="end">{display(tick.value)}</text>
        </g>)}
        {averageTicks.map(tick => <text key={`average-${tick.ratio}`} className="replenishment-monthly-chart-axis" x={width - padding.right + 6} y={padding.top + plotHeight * (1 - tick.ratio) + 3}>{display(tick.value)}</text>)}
        <text className="replenishment-monthly-chart-axis-label" x={8} y={padding.top - 9}>件</text>
        <text className="replenishment-monthly-chart-axis-label" x={width - 8} y={padding.top - 9} textAnchor="end">件/天</text>
        {data.map((item, index) => <line key={`month-grid-${String(item.month)}`} className="replenishment-monthly-chart-month-grid" x1={x(index)} x2={x(index)} y1={padding.top} y2={baselineY} />)}
      </>}
      <line className="replenishment-monthly-chart-baseline" x1={padding.left} x2={width - padding.right} y1={baselineY} y2={baselineY} />
      <path className="replenishment-monthly-chart-total-area" d={totalAreaPath} fill={`url(#${gradientId})`} />
      <path className="replenishment-monthly-chart-total-path" d={totalPath} />
      <path className="replenishment-monthly-chart-average-path" d={averagePath} />
      {data.map((item, index) => <g key={String(item.month)}>
        <circle className={`replenishment-monthly-chart-total-point ${activeIndex === index ? 'is-active' : ''}`} cx={x(index)} cy={totalY(item.total_sales)} r={activeIndex === index ? (compact ? 4 : 5) : (compact ? 2.5 : 3.5)} />
        <circle className={`replenishment-monthly-chart-average-point ${activeIndex === index ? 'is-active' : ''}`} cx={x(index)} cy={averageY(item.adjusted_daily_average)} r={activeIndex === index ? (compact ? 4 : 5) : (compact ? 2.5 : 3.5)} />
        {(!compact || index === 0 || index === data.length - 1) && <text className="replenishment-monthly-chart-month-label" x={x(index)} y={height - 5} textAnchor="middle">{String(item.month)}</text>}
      </g>)}
      {activeIndex !== null && <line className="replenishment-monthly-chart-crosshair" x1={x(activeIndex)} x2={x(activeIndex)} y1={padding.top} y2={baselineY} data-index={activeIndex} />}
      <rect
        className="replenishment-monthly-chart-hit-area"
        x={padding.left}
        y={padding.top}
        width={plotWidth}
        height={plotHeight}
        aria-label="按月份查看销量数据"
        onPointerDown={activatePoint}
        onPointerMove={activatePoint}
        onPointerLeave={event => { if (event.pointerType !== 'touch') clearActivePoint(); }}
        onPointerCancel={clearActivePoint}
      />
    </svg>
    {tooltip}
  </div>;
}

function ReplenishmentHistoryGroups({
  history,
  mode = 'main',
}: {
  history: ReplenishmentGroupRow['history'];
  mode?: 'main' | 'detail';
}) {
  const recent = history.recent_sales || { yesterday: null, day_before_yesterday: null, two_days_before: null };
  const recentItems = mode === 'detail'
    ? [['上前', recent.two_days_before], ['前天', recent.day_before_yesterday], ['昨天', recent.yesterday]] as const
    : [['昨天', recent.yesterday], ['前天', recent.day_before_yesterday], ['上前', recent.two_days_before]] as const;
  const sites = COUNTRY_ORDER.map((code, index) => ({ code, index, value: history.site_sales[code] }));
  if (mode !== 'detail') {
    sites.sort((left, right) => Number(right.value || 0) - Number(left.value || 0) || left.index - right.index);
  }
  const periods = [
    ['7天', history.period_sales?.days_7],
    ['14天', history.period_sales?.days_14],
    ['30天', history.period_sales?.days_30],
    ['90天', history.period_sales?.days_90],
  ] as const;
  const chartMonths = history.months?.length ? history.months : history.peak_months;
  return <div className={`replenishment-history-groups ${mode === 'main' ? 'replenishment-history-groups-main' : 'replenishment-history-groups-detail'}`}>
    <section className="replenishment-history-group replenishment-history-recent-group">
      <b>近3日</b>
      <div>{recentItems.map(([label, value]) => (
        <span className="replenishment-history-group-item" key={label}><em>{label}</em><strong>{display(value)}</strong></span>
      ))}</div>
    </section>
    <section className="replenishment-history-group replenishment-history-site-group">
      <b title={history.site_sales_period_start && history.site_sales_period_end
        ? `销量明细：${history.site_sales_period_start} 至 ${history.site_sales_period_end}`
        : '销量明细：暂无可用日期范围'}>
        4站点销量{history.site_sales_days ? `（${history.site_sales_days}天）` : ''}
      </b>
      <div>{sites.map(item => (
        <span className="replenishment-history-group-item" key={item.code}><em>{item.code}</em><strong>{display(item.value)}</strong></span>
      ))}</div>
    </section>
    <section className="replenishment-history-group replenishment-history-month-group">
      <b>{mode === 'detail' ? '周期销量' : '月份销量'}</b>
      {mode === 'detail'
        ? <div>{periods.map(([label, value]) => <span className="replenishment-history-group-item" key={label}><em>{label}</em><strong>{display(value)}</strong></span>)}</div>
        : <MonthlySalesTrendChart months={chartMonths} compact />}
    </section>
  </div>;
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

function shortObservationDate(value: string | null | undefined) {
  const match = String(value || '').match(/^\d{4}-(\d{2})-(\d{2})/);
  return match ? String(Number(match[1])) + '/' + String(Number(match[2])) : '';
}

function signedPriceChange(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const formatted = display(Number(value));
  return Number(value) > 0 ? '+' + formatted : formatted;
}

function observationDateLabel(change: ReplenishmentPriceChange) {
  const current = shortObservationDate(change.date);
  if (!current) return '';
  if (change.observed_as === '首次观察到' || Number(change.gap_days || 0) > 1) return current + ' 首次观察';
  const previous = shortObservationDate(change.previous_date);
  return previous ? previous + ' → ' + current : current;
}

function priceTone(change: ReplenishmentPriceChange | null | undefined) {
  if (!change) return 'price-neutral';
  if (change.status === '多SKU变价') {
    if (Number(change.representative_amount_change) > 0) return 'price-increase';
    if (Number(change.representative_amount_change) < 0) return 'price-decrease';
    return 'price-mixed';
  }
  if (change.status === '失去可售') return 'price-unavailable';
  if (change.status === '恢复可售') return 'price-restored';
  if (Number(change.amount_change) > 0) return 'price-increase';
  if (Number(change.amount_change) < 0) return 'price-decrease';
  return 'price-neutral';
}

function priceEventTooltip(code: string, price: ReplenishmentPriceCountry) {
  const change = price.latest_change;
  if (!change) {
    return price.current_price === null
      ? code + '暂无当前实际总价'
      : code + '当前实际总价 ' + display(price.current_price) + '；暂无变价记录';
  }
  if (change.status === '多SKU变价') {
    const representative = change.representative_sku
      ? '代表SKU：' + change.representative_sku
        + (change.representative_sales === null || change.representative_sales === undefined
          ? ''
          : '（30天销量：' + display(change.representative_sales) + '）')
      : '';
    const items = (change.items || []).map(item => {
      const dates = item.previous_date && item.date ? item.previous_date + ' → ' + item.date : item.date || '';
      const percent = item.percent_change === null || item.percent_change === undefined
        ? ''
        : '，变化率 ' + (Number(item.percent_change) * 100).toFixed(1) + '%';
      const gap = item.gap_days && item.gap_days > 1 ? '，间隔 ' + item.gap_days + ' 天，首次观察' : '';
      return (item.sku || 'SKU') + '：' + display(item.old_price) + ' → ' + display(item.new_price)
        + ' (' + signedPriceChange(item.amount_change) + percent + ')' + (dates ? ' · ' + dates : '') + gap;
    });
    return [representative, ...(items.length ? items : [code + '存在多个SKU价格变化，请展开SKU明细查看'])]
      .filter(Boolean)
      .join('\n');
  }
  const current = change.new_price === null || change.new_price === undefined ? price.current_price : change.new_price;
  const dateRange = change.previous_date && change.date ? change.previous_date + ' → ' + change.date : change.date || '';
  const sku = change.items?.[0]?.sku ? 'SKU：' + change.items[0].sku : '';
  const gap = change.gap_days && change.gap_days > 1 ? '观察间隔：' + change.gap_days + ' 天（首次观察）' : '';
  const amount = change.amount_change === null || change.amount_change === undefined
    ? ''
    : '变化：' + signedPriceChange(change.amount_change);
  const percent = change.percent_change === null || change.percent_change === undefined
    ? ''
    : '变化率：' + (Number(change.percent_change) * 100).toFixed(1) + '%';
  return [sku, code + '当前实际总价：' + display(current), dateRange, gap, amount, percent, change.observed_as || ''].filter(Boolean).join('\n');
}

function normalizedPriceHistory(points: ReplenishmentPriceHistoryPoint[] | undefined) {
  return [...(points || [])]
    .filter(point => point && String(point.date || '').trim())
    .sort((left, right) => String(left.date).localeCompare(String(right.date)))
    .map(point => ({
      ...point,
      current_price: point.current_price === null || point.current_price === undefined || !Number.isFinite(Number(point.current_price))
        ? null
        : Number(point.current_price),
      listing_price: point.listing_price === null || point.listing_price === undefined || !Number.isFinite(Number(point.listing_price))
        ? null
        : Number(point.listing_price),
      promotion_price: point.promotion_price === null || point.promotion_price === undefined || !Number.isFinite(Number(point.promotion_price))
        ? null
        : Number(point.promotion_price),
      is_promotion: Boolean(point.is_promotion),
    }));
}

function compactPriceDate(value: string) {
  const match = String(value || '').match(/^(?:\d{4}-)?(\d{1,2})-(\d{1,2})$/);
  return match ? `${Number(match[1])}/${Number(match[2])}` : String(value || '').slice(0, 10);
}

function priceHistoryTooltip(code: string, price: ReplenishmentPriceCountry, point: ReturnType<typeof normalizedPriceHistory>[number], representativeSku?: string | null) {
  const current = point.current_price === null ? '无当前价' : display(point.current_price);
  const launch = price.launch_price && point.current_price !== null
    ? `较开售 ${((point.current_price / price.launch_price - 1) * 100).toFixed(1)}%`
    : '';
  const change = point.amount_change === null || point.amount_change === undefined
    ? ''
    : `变化 ${signedPriceChange(point.amount_change)}${point.percent_change === null || point.percent_change === undefined ? '' : `（${(point.percent_change * 100).toFixed(1)}%）`}`;
  const gap = point.gap_days && point.gap_days > 1 ? `观察间隔 ${point.gap_days} 天 · 首次观察到` : '';
  return [
    `${compactPriceDate(point.date)} · ${code}`,
    `当前实际总价：${current}`,
    `Listing原价：${display(point.listing_price)}；优惠价：${display(point.promotion_price)}`,
    point.is_promotion ? '促销中' : '',
    launch,
    change,
    gap,
    point.anomaly ? `异常：${point.anomaly}` : '',
    representativeSku ? `代表SKU：${representativeSku}` : '',
  ].filter(Boolean).join('\n');
}

function PriceTrendMiniChart({
  code,
  price,
}: {
  code: typeof COUNTRY_ORDER[number];
  price: ReplenishmentPriceCountry;
}) {
  const data = normalizedPriceHistory(price.history);
  const chartId = useId();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState<ChartTooltipPosition | null>(null);
  const width = 190;
  const height = 58;
  const padding = { left: 4, right: 4, top: 5, bottom: 11 };
  const values = data.map(point => point.current_price).filter((value): value is number => value !== null && value > 0);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 1;
  const spread = Math.max(0.01, maximum - minimum);
  const axisMin = Math.max(0, minimum - spread * 0.12);
  const axisMax = maximum + spread * 0.12 || 1;
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const x = (index: number) => data.length <= 1 ? padding.left + plotWidth / 2 : padding.left + index * plotWidth / (data.length - 1);
  const y = (value: number) => padding.top + plotHeight - ((value - axisMin) / Math.max(0.01, axisMax - axisMin)) * plotHeight;
  const available = data.map((point, index) => point.current_price === null ? null : { point, index, x: x(index), y: y(point.current_price) });
  const latestPoint = data[data.length - 1];
  const segments = data.slice(1).flatMap((point, index) => {
    const previous = available[index];
    const current = available[index + 1];
    if (!previous || !current) return [];
    return [{ previous, current, gap: Boolean(point.gap_days && point.gap_days > 1), promo: Boolean(previous.point.is_promotion || point.is_promotion) }];
  });
  const clearActivePoint = useCallback(() => {
    setActiveIndex(null);
    setTooltipPosition(null);
  }, []);
  useEffect(() => {
    if (activeIndex !== null && activeIndex >= data.length) clearActivePoint();
  }, [activeIndex, clearActivePoint, data.length]);
  useEffect(() => {
    if (activeIndex === null) return undefined;
    const clearOnViewportChange = () => clearActivePoint();
    window.addEventListener('scroll', clearOnViewportChange, true);
    window.addEventListener('resize', clearOnViewportChange);
    return () => {
      window.removeEventListener('scroll', clearOnViewportChange, true);
      window.removeEventListener('resize', clearOnViewportChange);
    };
  }, [activeIndex, clearActivePoint]);
  const activatePoint = useCallback((event: ReactPointerEvent<SVGRectElement>) => {
    const svg = svgRef.current;
    const rect = svg?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height || !data.length) return;
    const localX = (event.clientX - rect.left) * width / rect.width;
    const ratio = Math.max(0, Math.min(1, (localX - padding.left) / plotWidth));
    const nextIndex = data.length <= 1 ? 0 : Math.max(0, Math.min(data.length - 1, Math.round(ratio * (data.length - 1))));
    const point = data[nextIndex]!;
    const screenX = rect.left + x(nextIndex) / width * rect.width;
    const numeric = point.current_price === null ? null : y(point.current_price);
    const screenY = rect.top + (numeric === null ? height / 2 : numeric) / height * rect.height;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
    const anchoredX = Math.max(8, Math.min(viewportWidth - 8, screenX));
    const anchoredY = Math.max(8, Math.min(window.innerHeight - 8, screenY));
    setActiveIndex(nextIndex);
    setTooltipPosition({
      left: anchoredX,
      top: anchoredY,
      horizontal: anchoredX < 135 ? 'right' : anchoredX > viewportWidth - 135 ? 'left' : 'center',
      vertical: anchoredY > 135 ? 'above' : 'below',
    });
  }, [data, height, padding.left, plotWidth, width, x, y]);
  if (!data.length) return null;
  const portalIsDark = typeof document !== 'undefined' && Boolean(document.querySelector('.app-shell.dark-mode'));
  const activePoint = activeIndex === null ? null : data[activeIndex];
  const tooltip = activePoint && tooltipPosition && typeof document !== 'undefined'
    ? createPortal(
      <div
        className={`replenishment-price-chart-tooltip tooltip-${tooltipPosition.horizontal} tooltip-${tooltipPosition.vertical}${portalIsDark ? ' is-dark' : ''}`}
        role="tooltip"
        aria-live="polite"
        style={{ left: tooltipPosition.left, top: tooltipPosition.top }}
      >
        <strong>{priceHistoryTooltip(code, price, activePoint, price.representative_sku).split('\n')[0]}</strong>
        <div>当前实际总价 <b>{activePoint.current_price === null ? '无当前价' : display(activePoint.current_price)}</b></div>
        <div>原价 / 优惠 <b>{display(activePoint.listing_price)} / {display(activePoint.promotion_price)}</b></div>
        {activePoint.is_promotion && <small className="replenishment-price-chart-promo-label">促销中</small>}
        {price.launch_price !== null && price.launch_price !== undefined && activePoint.current_price !== null && <small>较开售 {((activePoint.current_price / price.launch_price - 1) * 100).toFixed(1)}%</small>}
        {activePoint.amount_change !== null && activePoint.amount_change !== undefined && <small>{signedPriceChange(activePoint.amount_change)} · {activePoint.percent_change === null || activePoint.percent_change === undefined ? '' : `${(activePoint.percent_change * 100).toFixed(1)}%`}</small>}
        {activePoint.gap_days && activePoint.gap_days > 1 && <small>间隔 {activePoint.gap_days} 天 · 首次观察到</small>}
        {activePoint.anomaly && <small>异常：{activePoint.anomaly}</small>}
        {price.representative_sku && <small>代表SKU：{price.representative_sku}</small>}
      </div>,
      document.body,
    )
    : null;
  return <div className="replenishment-price-trend" aria-label={`${code} 31天价格趋势`}>
    <div className="replenishment-price-trend-caption">
      <span><i className="replenishment-price-trend-line" />价格</span>
      <span className="replenishment-price-trend-promo"><i />促销</span>{data.length < 2 && <em className="replenishment-price-trend-empty">暂无趋势</em>}
    </div>
    <svg ref={svgRef} className="replenishment-price-trend-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${code}当前实际总价阶梯趋势`}>
      <line className="replenishment-price-trend-baseline" x1={padding.left} x2={width - padding.right} y1={padding.top + plotHeight} y2={padding.top + plotHeight} />
      {segments.map(segment => <path
        key={`${segment.previous.index}-${segment.current.index}`}
        className={`replenishment-price-trend-segment${segment.promo ? ' is-promo' : ''}${segment.gap ? ' is-gap' : ''}`}
        d={`M ${segment.previous.x.toFixed(2)} ${segment.previous.y.toFixed(2)} H ${segment.current.x.toFixed(2)} V ${segment.current.y.toFixed(2)}`}
      />)}
      {available.map((item, index) => item && <circle key={`${item.point.date}-${index}`} className={`replenishment-price-trend-point${item.point.is_promotion ? ' is-promo' : ''}${activeIndex === index ? ' is-active' : ''}`} cx={item.x} cy={item.y} r={activeIndex === index ? 3.4 : 2} />)}
      {available.some(item => item === null) && data.map((point, index) => point.current_price === null && <circle key={`unavailable-${point.date}-${index}`} className="replenishment-price-trend-unavailable" cx={x(index)} cy={padding.top + plotHeight} r="2.4" />)}
      {activeIndex !== null && <line className="replenishment-price-trend-crosshair" x1={x(activeIndex)} x2={x(activeIndex)} y1={padding.top} y2={padding.top + plotHeight} />}
      <text className="replenishment-price-trend-date" x={padding.left} y={height - 1}>{compactPriceDate(data[0]!.date)}</text>
      <text className="replenishment-price-trend-date" x={width - padding.right} y={height - 1} textAnchor="end">{compactPriceDate(latestPoint!.date)}</text>
      <rect className="replenishment-price-trend-hit-area" x={padding.left} y={padding.top} width={plotWidth} height={plotHeight} aria-label="按日期查看价格" onPointerDown={activatePoint} onPointerMove={activatePoint} onPointerLeave={event => { if (event.pointerType !== 'touch') clearActivePoint(); }} onPointerCancel={clearActivePoint} />
    </svg>
    {tooltip}
  </div>;
}
function CountryPriceChange({
  code,
  pricing,
}: {
  code: typeof COUNTRY_ORDER[number];
  pricing?: ReplenishmentGroupRow['pricing'];
}) {
  const price = pricing?.countries[code];
  if (!price) return null;
  const change = price.latest_change;
  const hasHistory = Boolean(price.history?.length);
  let title = price.current_price === null ? '无当前价' : '现价 ' + display(price.current_price);
  let subtitle = change ? observationDateLabel(change) : '暂无变价';
  if (change?.status === '变价') {
    if (price.current_price === null) {
      title = '无当前价';
      subtitle = observationDateLabel(change) || '暂无当前价';
    } else {
      title = '现价 ' + display(price.current_price) + ' (' + signedPriceChange(change.amount_change) + ')';
    }
  } else if (change?.status === '多SKU变价') {
    const representativePrice = change.representative_new_price;
    const representativeAmount = change.representative_amount_change;
    if (representativePrice !== null && representativePrice !== undefined) {
      title = '现价 ' + display(representativePrice)
        + (representativeAmount === null || representativeAmount === undefined
          ? ''
          : ' (' + signedPriceChange(representativeAmount) + ')');
      subtitle = (observationDateLabel(change) || '暂无变价') + (change.representative_sku ? ' · 代表SKU' : '');
    } else {
      title = '多SKU变价';
      subtitle = observationDateLabel(change) || '展开查看';
    }
  } else if (change?.status === '失去可售') {
    title = '无当前价';
    subtitle = (observationDateLabel(change) + ' 失去可售').trim();
  } else if (change?.status === '恢复可售') {
    title = change.new_price === null || change.new_price === undefined
      ? '恢复可售'
      : '现价 ' + display(change.new_price) + '（恢复）';
  }
  const content = <div className={'replenishment-country-price ' + priceTone(change) + (hasHistory ? ' has-trend' : '')}>
    <div className="replenishment-country-price-summary">
      <strong>{title}</strong>
      <small>{subtitle}</small>
    </div>
    {hasHistory && <PriceTrendMiniChart code={code} price={price} />}
  </div>;
  return hasHistory
    ? content
    : <Tooltip title={<span style={{ whiteSpace: 'pre-line' }}>{priceEventTooltip(code, price)}</span>}>{content}</Tooltip>;
}
function CountryCell({
  code,
  metric,
  pricing,
}: {
  code: typeof COUNTRY_ORDER[number];
  metric: ReplenishmentCountryMetric;
  pricing?: ReplenishmentGroupRow['pricing'];
}) {
  const reasonText = metric.reasons.join('；');
  return <div className="replenishment-country-cell" data-section={code} role="gridcell">
    <div className="replenishment-country-main">
      <span>单量 <strong>{display(metric.units)}</strong></span>
      <span className={`replenishment-margin ${marginClass(metric.margin)}`}>{percent(metric.margin)}</span>
    </div>
    {metric.reasons.length
      ? <Tooltip title={reasonText}><div className="replenishment-reasons">{metric.reasons.slice(0, 2).map((reason, index) => <span key={`${reason}-${index}`}>{reason}</span>)}</div></Tooltip>
      : <span className="replenishment-country-ok">无异常</span>}
    <CountryPriceChange code={code} pricing={pricing} />
  </div>;
}

export function DecisionBoardHeader() {
  return <div className="replenishment-board-grid replenishment-board-header" role="row">
    {['产品识别', 'DE', 'FR', 'ES', 'IT', '库存矩阵', '趋势测算', '销量画像', '补货决策'].map(label => (
      <div key={label} role="columnheader">{label}</div>
    ))}
  </div>;
}

function ListingPriceTiles({ row }: { row: Row }) {
  return <div className="replenishment-price-grid" aria-label="四站Listing价格">
    {COUNTRY_ORDER.map(code => {
      const launch = row[code + '_开售价'];
      const current = row[code + '_当前实际总价'];
      const rawDelta = row[code + '_较开售价变化'];
      const numericDelta = rawDelta === null || rawDelta === undefined || rawDelta === '' || !Number.isFinite(Number(rawDelta))
        ? null
        : Number(rawDelta);
      const deltaClass = numericDelta === null
        ? 'price-missing'
        : numericDelta < 0
          ? 'price-decrease'
          : numericDelta > 0
            ? 'price-increase'
            : 'price-neutral';
      return <div
        className={'replenishment-price-tile ' + deltaClass}
        key={code}
        title={code + '：开售价 ' + display(launch) + '；当前实际总价 ' + display(current) + '；较开售价 ' + (numericDelta === null ? '—' : (numericDelta * 100).toFixed(1) + '%')}
      >
        <strong>{code}</strong>
        <MetricLine label="开售" value={launch} />
        <MetricLine label="现价" value={current} />
        <div className="replenishment-price-delta">
          <span>较开售</span>
          <b>{numericDelta === null ? '—' : (numericDelta * 100).toFixed(1) + '%'}</b>
        </div>
      </div>;
    })}
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
    {details.sales_history
      ? <section className="replenishment-history-detail">
        <h4>{details.sales_history.title || '销量画像'}</h4>
        <ReplenishmentHistoryGroups history={details.sales_history} mode="detail" />
        {details.sales_history.available
          ? <MonthlySalesTrendChart months={details.sales_history.months} />
          : <div className="replenishment-history-empty">往月销量原始表未上传或该ASIN暂无四站销量，不影响建议补货数量。</div>}
      </section>
      : <div className="replenishment-history-empty replenishment-history-detail">往月销量原始表未上传或该ASIN暂无四站销量，不影响建议补货数量。</div>}
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
              <MetricLine label="昨天" value={row['昨天销量']} />
              <MetricLine label="前天" value={row['前天销量']} />
              <MetricLine label="上前" value={row['上前销量']} />
              <MetricLine label="7天" value={row['7天销量']} />
              <MetricLine label="14天" value={row['14天销量']} />
              <MetricLine label="30天" value={row['30天销量']} />
              <MetricLine label="90天" value={row['90天销量']} />
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
              <MetricLine label="最近限时开始" value={row['最近促销开始日期']} />
              <MetricLine label="促销截止" value={row['最近促销截止日期']} />
              <MetricLine label="促销折扣" value={row['最近促销折扣'] === null || row['最近促销折扣'] === undefined ? null : `${display(row['最近促销折扣'])}%`} />
            </section>
            <section className="replenishment-sku-pricing-section"><h4>价格与毛利</h4>
              <div className="replenishment-sku-pricing-groups">
                <div className="replenishment-sku-pricing-group">
                  <h5>Listing价格</h5>
                  <ListingPriceTiles row={row} />
                </div>
                <div className="replenishment-sku-pricing-group">
                  <h5>分站点毛利率</h5>
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
                </div>
              </div>
            </section>
          </div>
        </article>
      )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无SKU明细" />}
    </div>
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
  const hasMonthlyHistory = Boolean(row.history.months?.length || row.history.peak_months?.length);
  return <div className={`replenishment-row-shell ${expanded ? 'is-expanded' : ''}`}>
    <div
      className={'replenishment-board-grid replenishment-board-row '
        + (row.pricing ? 'has-country-price ' : '')
        + (hasMonthlyHistory ? 'has-monthly-history' : '')}
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
        <SkuImagePreview
          image={row.identity.image}
          className="replenishment-asin-image"
          placeholderClassName="replenishment-asin-image-placeholder"
          alt={`${row.identity.asin}库存图片`}
          placeholderLabel={`${row.identity.asin}暂无图片`}
        />
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
      {COUNTRY_ORDER.map(code => <CountryCell key={code} code={code} metric={row.countries[code]} pricing={row.pricing} />)}
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
        <ReplenishmentHistoryGroups history={row.history} mode="main" />
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
  const [pricingLoading, setPricingLoading] = useState(false);
  const [pricingError, setPricingError] = useState('');
  const [error, setError] = useState('');
  const [appliedDevelopers, setAppliedDevelopers] = useState<string[]>([]);
  const [appliedMinQty, setAppliedMinQty] = useState(30);
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
  const sectionQueryRef = useRef({ page: 1, pageSize: 50, search: '', sort: '建议补货数量:desc', initialized: false });
  const filterKeyRef = useRef('');
  const pricingRequestId = useRef(0);
  const queryRequestId = useRef(0);
  const queryAbortRef = useRef<AbortController | undefined>(undefined);
  const mainAbortRef = useRef<AbortController | undefined>(undefined);

  const replenishmentParams = useCallback(
    (): Record<string, string> => ({
      ...(appliedDevelopers.length ? { developers: appliedDevelopers.join(',') } : {}),
      min_qty: String(appliedMinQty),
    }),
    [appliedDevelopers, appliedMinQty],
  );

  const loadPricing = useCallback(async (nextRows: ReplenishmentGroupRow[]) => {
    const current = ++pricingRequestId.current;
    const groupIds = nextRows.map(row => row.group_id).filter(Boolean);
    if (!groupIds.length) {
      setPricingLoading(false);
      setPricingError('');
      return;
    }
    setPricingLoading(true);
    setPricingError('');
    try {
      const result = await api.replenishmentPricing(groupIds);
      if (current !== pricingRequestId.current) return;
      setSection(currentSection => currentSection ? {
        ...currentSection,
        group_rows: (currentSection.group_rows || []).map(row => ({
          ...row,
          pricing: result.rows[row.group_id] ?? null,
        })),
      } : currentSection);
    } catch (priceError) {
      if (current === pricingRequestId.current) setPricingError(priceError instanceof Error ? priceError.message : '价格与趋势加载失败');
    } finally {
      if (current === pricingRequestId.current) setPricingLoading(false);
    }
  }, []);
  const load = useCallback(async () => {
    const current = ++requestId.current;
    queryRequestId.current += 1;
    queryAbortRef.current?.abort();
    mainAbortRef.current?.abort();
    const controller = new AbortController();
    mainAbortRef.current = controller;
    pricingRequestId.current += 1;
    const filterKey = JSON.stringify(replenishmentParams());
    const filterChanged = filterKeyRef.current !== filterKey;
    if (filterChanged) {
      const nextSort = sectionQueryRef.current.sort;
      sectionQueryRef.current = { page: 1, pageSize: sectionQueryRef.current.pageSize, search: appliedSearch, sort: nextSort, initialized: true };
      setDetails({});
      setExpanded(new Set());
    }
    filterKeyRef.current = filterKey;
    setLoading(true);
    setError('');
    try {
      const query = sectionQueryRef.current;
      const [sortBy, sortOrder] = query.sort.split(':');
      const next = await api.dashboard('replenishment', {
        ...replenishmentParams(),
        page: String(query.page),
        page_size: String(query.pageSize),
        ...(query.search ? { search: query.search } : {}),
        sort_by: sortBy,
        sort_order: sortOrder,
        include_pricing: 'false',
      }, controller.signal);
      if (current !== requestId.current) return;
      const nextSection = next.sections.find(item => item.key === 'detail');
      setPayload(next);
      setSection(nextSection);
      void loadPricing(nextSection?.group_rows || []);
      return true;
    } catch (loadError) {
      if (current === requestId.current && !controller.signal.aborted) setError(loadError instanceof Error ? loadError.message : '读取补货管理失败');
      return false;
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, [appliedSearch, loadPricing, replenishmentParams]);

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
    const normalizedSearch = nextSearch.trim();
    queryAbortRef.current?.abort();
    mainAbortRef.current?.abort();
    const controller = new AbortController();
    queryAbortRef.current = controller;
    const currentRequest = ++queryRequestId.current;
    requestId.current += 1;
    pricingRequestId.current += 1;
    sectionQueryRef.current = { page, pageSize, search: normalizedSearch, sort: nextSort, initialized: true };
    setQueryLoading(true);
    setError('');
    try {
      const next = await api.dashboardSection('replenishment', 'detail', {
        ...replenishmentParams(),
        page: String(page),
        page_size: String(pageSize),
        ...(normalizedSearch ? { search: normalizedSearch } : {}),
        sort_by: sortBy,
        sort_order: sortOrder,
        include_pricing: 'false',
      }, controller.signal);
      if (currentRequest !== queryRequestId.current) return false;
      setSection(next);
      void loadPricing(next.group_rows || []);
      setPricingError('');
      setAppliedSearch(normalizedSearch);
      setExpanded(new Set());
      return true;
    } catch (pageError) {
      if (controller.signal.aborted || currentRequest !== queryRequestId.current) return false;
      setError(pageError instanceof Error ? pageError.message : '读取补货分页失败');
      return false;
    } finally {
      if (currentRequest === queryRequestId.current) setQueryLoading(false);
    }
  }, [appliedSearch, loadPricing, replenishmentParams, section?.page_size, sort]);

  const applySearch = (value: string) => {
    setSearch(value);
    const nextSearch = value.trim();
    if (nextSearch === appliedSearch) return;
    setAppliedSearch(nextSearch);
    sectionQueryRef.current = {
      page: 1,
      pageSize: section?.page_size || sectionQueryRef.current.pageSize,
      search: nextSearch,
      sort,
      initialized: true,
    };
  };
  const resetFilters = () => {
    setSearch('');
    setAppliedDevelopers([]);
    setAppliedMinQty(30);
    setAppliedSearch('');
    setSort('建议补货数量:desc');
    sectionQueryRef.current = { page: 1, pageSize: section?.page_size || 50, search: '', sort: '建议补货数量:desc', initialized: true };
  };

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
    const operationKey = `disable-${asin}`;
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
      message.success({ key: operationKey, content: `${asin}已设为不补货并移出矩阵` });
      if (shouldLoadPreviousPage) {
        const refreshed = await loadSection({ page: currentPage - 1, pageSize });
        if (refreshed === false) message.warning({ key: operationKey, content: `${asin}已设为不补货，但页面刷新失败`, duration: 6 });
      }
    } catch (switchError) {
      const detail = switchError instanceof Error ? switchError.message : '保存补货开关失败';
      setError(detail);
      message.error(`${asin}设为不补货失败：${detail}`);
    } finally {
      setSwitchSavingAsin('');
    }
  };

  const rows = section?.group_rows || payload?.group_rows || [];
  const developerOptions = payload?.filters.developers || [];
  const [exportSortBy, exportSortOrder] = sort.split(':');
  const exportParams = { ...replenishmentParams(), ...(appliedSearch ? { search: appliedSearch } : {}), sort_by: exportSortBy, sort_order: exportSortOrder };
  const exportHref = `/api/dashboard/replenishment/export.xlsx?${new URLSearchParams(exportParams).toString()}`;
  const sortLabel = useMemo(() => SORT_OPTIONS.find(item => item.value === sort)?.label || '建议补货数量：高到低', [sort]);
  return <>
    <div className="page-heading replenishment-page-heading">
      <div><Typography.Title level={2}>补货管理</Typography.Title><Typography.Text type="secondary">ASIN主行汇总所有SKU销量与库存；导出将使用当前筛选条件。</Typography.Text></div>
      <Space><Button icon={<DownloadOutlined />} disabled={loading || queryLoading || (!section?.total && !rows.length)} title="导出全部匹配行，不限当前页" href={exportHref} onClick={event => { event.preventDefault(); void downloadWithFeedback(exportHref, '补货建议.xlsx', '补货筛选结果'); }}>导出筛选结果</Button><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void (async () => { const refreshed = await load(); if (refreshed) message.success('补货数据已刷新'); else message.error('补货数据刷新失败'); })()}>刷新</Button></Space>
    </div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="补货管理读取失败" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    <Card className="filter-card replenishment-filter-card">
      <Space wrap>
        <Typography.Text strong>开发员</Typography.Text>
        <ConfirmFilterSelect
          ariaLabel="开发员筛选"
          mode="multiple"
          value={appliedDevelopers}
          options={developerOptions.map(value => ({ value, label: value }))}
          onConfirm={value => setAppliedDevelopers(Array.isArray(value) ? value.map(String) : [])}
          placeholder="全部开发员"
          style={{ minWidth: 220 }}
        />
        <Typography.Text strong>补货数量</Typography.Text>
        <ConfirmFilterSelect
          ariaLabel="建议补货数量门槛"
          mode="single"
          value={appliedMinQty}
          normalizeValue={value => Number(value ?? 30)}
          options={MIN_QTY_OPTIONS}
          onConfirm={value => setAppliedMinQty(value === undefined ? 30 : Number(value))}
          placeholder="补货数量门槛"
          style={{ width: 150 }}
        />
        <Input.Search
          allowClear
          value={search}
          placeholder="搜索ASIN、SKU、店铺、标签"
          onChange={event => setSearch(event.target.value)}
          onSearch={applySearch}
          style={{ width: 250 }}
        />
        <FilterActions onReset={resetFilters} />
        <Typography.Text strong>排序</Typography.Text>
        <ConfirmFilterSelect
          ariaLabel="补货排序"
          mode="single"
          value={sort}
          normalizeValue={value => value || '建议补货数量:desc'}
          options={[...SORT_OPTIONS]}
          onConfirm={value => {
            const nextSort = value ? String(value) : '建议补货数量:desc';
            setSort(nextSort);
            void loadSection({ page: 1, nextSort });
          }}
          placeholder="建议补货数量：高到低"
          style={{ width: 205 }}
        />
        {appliedSearch && <Tag>搜索：{appliedSearch}</Tag>}
      </Space>
    </Card>
    <div className="metric-grid replenishment-metric-grid">{(payload?.metrics || []).map(item => <Card key={item.name}><Statistic title={item.name} value={Number(item.value) || 0} precision={0} /></Card>)}</div>
    {pricingLoading && <Typography.Text type="secondary" className="replenishment-pricing-status">价格与趋势加载中…</Typography.Text>}
    {pricingError && <Alert className="section-load-error" type="warning" showIcon message="价格与趋势加载失败" description={pricingError} action={<Button size="small" onClick={() => void loadPricing(rows)}>重试</Button>} />}
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
