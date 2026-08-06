import { Tooltip } from 'antd';
import type { DashboardColumn, DashboardSection } from './api';

export type DashboardMatrixKind = 'product-detail' | 'low-margin' | 'slow-moving';

const PRODUCT_GROUPS = {
  identity: ['SKU', 'ASIN', 'Rating'],
  launch: ['开售时间', '开售天数'],
  inventory: ['可售数量', '可售天数'],
  recent: ['日均销量', '昨天销量', '前天销量', '上前销量', '7天销量', '14天销量', '30天销量', '90天销量'],
  countries: [
    '德国开售价格', '德国销量', '德国毛利率', '德国广告费占比',
    '法国开售价格', '法国销量', '法国毛利率', '法国广告费占比',
    '西班牙开售价格', '西班牙销量', '西班牙毛利率', '西班牙广告费占比',
    '意大利开售价格', '意大利销量', '意大利毛利率', '意大利广告费占比',
  ],
  overall: ['销售额', '毛利润', '毛利率'],
} as const;

const LOW_MARGIN_GROUPS = {
  identity: ['SKU', 'ASIN', '开发员'],
  site: ['国家', '销量'],
  amount: ['销售额', '毛利润'],
  risk: ['毛利率'],
} as const;

const SLOW_MOVING_GROUPS = {
  identity: ['SKU', 'ASIN', '开发员'],
  overview: ['90天以上库存数合计', '90天以上占用资金合计', '库存计提', '弃置费'],
  stock: ['91-180天库存数', '181-330天库存数', '331-365天库存数', '366-455天库存数', '456天以上库存数'],
  capital: ['91-180天占用资金', '181-330天占用资金', '331-365天占用资金', '366-455天占用资金', '456天占用资金'],
} as const;

export const PRODUCT_MATRIX_FIELDS = Object.values(PRODUCT_GROUPS).flat();
export const LOW_MARGIN_MATRIX_FIELDS = Object.values(LOW_MARGIN_GROUPS).flat();
export const SLOW_MOVING_MATRIX_FIELDS = Object.values(SLOW_MOVING_GROUPS).flat();

const COUNTRY_GROUPS = [
  { code: 'DE', name: '德国' },
  { code: 'FR', name: '法国' },
  { code: 'ES', name: '西班牙' },
  { code: 'IT', name: '意大利' },
] as const;

const PRODUCT_HEADERS = ['产品识别', '开售信息', '库存效率', '近期销量', 'DE', 'FR', 'ES', 'IT', '整体收益'];
const LOW_MARGIN_HEADERS = ['产品识别', '站点销量', '收益金额', '毛利风险'];
const SLOW_MOVING_HEADERS = ['产品识别', '风险总览', '库存库龄', '资金库龄'];
const AGING_LABELS = ['91–180', '181–330', '331–365', '366–455', '456+'];

export function dashboardMatrixKind(page: string, sectionKey: string): DashboardMatrixKind | null {
  if (page === 'products' && sectionKey === 'detail') return 'product-detail';
  if (page === 'products' && sectionKey === 'low-margin') return 'low-margin';
  if (page === 'slow-moving' && sectionKey === 'detail') return 'slow-moving';
  return null;
}

function hasValue(value: unknown) {
  return value !== null && value !== undefined && value !== '';
}

function numeric(value: unknown): number | null {
  if (!hasValue(value)) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function amountInWan(value: number) {
  return `${(value / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 万`;
}

function launchPrice(value: unknown) {
  const number = numeric(value);
  return number === null
    ? '-'
    : number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function createFormatter(columns: DashboardColumn[]) {
  const metadata = new Map(columns.map(column => [column.key, column]));
  return (key: string, value: unknown) => {
    if (!hasValue(value)) return '-';
    const column = metadata.get(key);
    const number = numeric(value);
    if (number === null || column?.format === 'text' || column?.type === 'string') return String(value);
    const precision = Math.min(2, Math.max(0, Number.isFinite(Number(column?.precision)) ? Number(column?.precision) : 2));
    if (column?.format === 'percent' || column?.type === 'percent') {
      return `${(number * 100).toLocaleString('zh-CN', { maximumFractionDigits: precision })}%`;
    }
    if (column?.format === 'amount' || column?.type === 'currency') return amountInWan(number);
    return number.toLocaleString('zh-CN', { maximumFractionDigits: precision });
  };
}

export function marginTone(value: unknown) {
  const number = numeric(value);
  if (number === null) return 'tone-missing';
  if (number < 0) return 'tone-negative';
  if (number < 0.1) return 'tone-low';
  if (number < 0.2) return 'tone-warning';
  return 'tone-good';
}

export function adRatioTone(value: unknown) {
  const number = numeric(value);
  if (number === null) return 'tone-missing';
  if (number <= 0.1) return 'tone-good';
  if (number <= 0.2) return 'tone-warning';
  return 'tone-negative';
}

function ratingParts(value: unknown) {
  const text = hasValue(value) ? String(value).trim() : '';
  const match = text.match(/^(\d+)(?:\(([-+]?\d+(?:\.\d+)?)\))?$/);
  if (!match) return { text: text || '暂无Rating', score: null as number | null };
  return { text, score: match[2] === undefined ? null : Number(match[2]) };
}

export function ratingTone(value: unknown) {
  const score = ratingParts(value).score;
  if (score === null || !Number.isFinite(score)) return 'rating-missing';
  if (score >= 4.3) return 'rating-good';
  if (score >= 3.5) return 'rating-warning';
  return 'rating-danger';
}

function CompactText({ value, className = '' }: { value: unknown; className?: string }) {
  const text = hasValue(value) ? String(value) : '-';
  return <Tooltip title={text}><span className={`dashboard-matrix-ellipsis ${className}`}>{text}</span></Tooltip>;
}

function Metric({
  label,
  value,
  className = '',
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return <span className={`dashboard-matrix-metric ${className}`}>
    <small>{label}</small>
    <strong>{value}</strong>
  </span>;
}

function MatrixHeader({ labels, kind }: { labels: string[]; kind: DashboardMatrixKind }) {
  return <div className={`dashboard-matrix-grid dashboard-matrix-header matrix-${kind}`} role="row" aria-rowindex={1}>
    {labels.map(label => <div key={label} role="columnheader">{label}</div>)}
  </div>;
}

function ProductRow({
  row,
  index,
  format,
}: {
  row: Record<string, unknown>;
  index: number;
  format: (key: string, value: unknown) => string;
}) {
  const rating = ratingParts(row.Rating);
  return <div className="dashboard-matrix-grid dashboard-matrix-row matrix-product-detail" role="row" aria-rowindex={index + 2} tabIndex={0} data-row-index={index}>
    <div className="dashboard-matrix-identity" role="gridcell" data-section="产品识别">
      <CompactText value={row.SKU} className="dashboard-matrix-sku" />
      <CompactText value={row.ASIN} />
      <span className={`dashboard-matrix-rating ${ratingTone(row.Rating)}`}>{rating.text}</span>
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-lines dashboard-launch-cell" role="gridcell" data-section="开售信息">
      <Metric label="开售时间" value={format('开售时间', row['开售时间'])} />
      <Metric label="开售天数" value={format('开售天数', row['开售天数'])} />
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-lines" role="gridcell" data-section="库存效率">
      <Metric label="可售" value={format('可售数量', row['可售数量'])} />
      <Metric label="可售天数" value={format('可售天数', row['可售天数'])} />
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-mini-grid recent-sales-grid" role="gridcell" data-section="近期销量">
      {[
        ['日均', '日均销量'], ['昨天', '昨天销量'], ['前天', '前天销量'], ['上前', '上前销量'],
        ['7天', '7天销量'], ['14天', '14天销量'], ['30天', '30天销量'], ['90天', '90天销量'],
      ].map(([label, key]) => <Metric key={key} label={label} value={format(key, row[key])} />)}
    </div>
    {COUNTRY_GROUPS.map(country => {
      const priceKey = `${country.name}开售价格`;
      const salesKey = `${country.name}销量`;
      const marginKey = `${country.name}毛利率`;
      const adKey = `${country.name}广告费占比`;
      return <div className="dashboard-matrix-cell dashboard-country-matrix" role="gridcell" data-section={country.code} key={country.code}>
        <Metric label="开售价" value={launchPrice(row[priceKey])} />
        <Metric label="销量" value={format(salesKey, row[salesKey])} />
        <Metric label="毛利率" value={format(marginKey, row[marginKey])} className={marginTone(row[marginKey])} />
        <Metric label="广告占比" value={format(adKey, row[adKey])} className={adRatioTone(row[adKey])} />
      </div>;
    })}
    <div className="dashboard-matrix-cell dashboard-matrix-lines dashboard-overall-cell" role="gridcell" data-section="整体收益">
      <Metric label="销售额" value={format('销售额', row['销售额'])} />
      <Metric label="毛利润" value={format('毛利润', row['毛利润'])} />
      <Metric label="毛利率" value={format('毛利率', row['毛利率'])} className={marginTone(row['毛利率'])} />
    </div>
  </div>;
}

function LowMarginRow({
  row,
  index,
  format,
}: {
  row: Record<string, unknown>;
  index: number;
  format: (key: string, value: unknown) => string;
}) {
  const margin = numeric(row['毛利率']);
  const riskLabel = margin === null ? '暂无数据' : margin < 0 ? '负毛利' : margin < 0.1 ? '高风险' : margin < 0.2 ? '需关注' : '健康';
  return <div className="dashboard-matrix-grid dashboard-matrix-row matrix-low-margin" role="row" aria-rowindex={index + 2} tabIndex={0} data-row-index={index}>
    <div className="dashboard-matrix-identity" role="gridcell" data-section="产品识别">
      <CompactText value={row.SKU} className="dashboard-matrix-sku" />
      <CompactText value={row.ASIN} />
      <CompactText value={row['开发员']} />
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-lines" role="gridcell" data-section="站点销量">
      <Metric label="国家" value={format('国家', row['国家'])} />
      <Metric label="销量" value={format('销量', row['销量'])} />
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-lines" role="gridcell" data-section="收益金额">
      <Metric label="销售额" value={format('销售额', row['销售额'])} />
      <Metric label="毛利润" value={format('毛利润', row['毛利润'])} />
    </div>
    <div className={`dashboard-margin-risk ${marginTone(row['毛利率'])}`} role="gridcell" data-section="毛利风险">
      <small>毛利率</small>
      <strong>{format('毛利率', row['毛利率'])}</strong>
      <span>{riskLabel}</span>
    </div>
  </div>;
}

function AgingGrid({
  keys,
  row,
  format,
}: {
  keys: readonly string[];
  row: Record<string, unknown>;
  format: (key: string, value: unknown) => string;
}) {
  return <div className="dashboard-aging-grid">
    {keys.map((key, index) => {
      const active = Number(row[key] || 0) > 0;
      return <Metric
        key={key}
        label={AGING_LABELS[index]}
        value={format(key, row[key])}
        className={active ? `aging-level-${index + 1}` : ''}
      />;
    })}
  </div>;
}

function SlowMovingRow({
  row,
  index,
  format,
}: {
  row: Record<string, unknown>;
  index: number;
  format: (key: string, value: unknown) => string;
}) {
  return <div className="dashboard-matrix-grid dashboard-matrix-row matrix-slow-moving" role="row" aria-rowindex={index + 2} tabIndex={0} data-row-index={index}>
    <div className="dashboard-matrix-identity" role="gridcell" data-section="产品识别">
      <CompactText value={row.SKU} className="dashboard-matrix-sku" />
      <CompactText value={row.ASIN} />
      <CompactText value={row['开发员']} />
    </div>
    <div className="dashboard-matrix-cell dashboard-matrix-mini-grid slow-overview-grid" role="gridcell" data-section="风险总览">
      <Metric label="90+库存" value={format('90天以上库存数合计', row['90天以上库存数合计'])} />
      <Metric label="占用资金" value={format('90天以上占用资金合计', row['90天以上占用资金合计'])} />
      <Metric label="库存计提" value={format('库存计提', row['库存计提'])} />
      <Metric label="弃置费" value={format('弃置费', row['弃置费'])} className={Number(row['弃置费'] || 0) > 0 ? 'tone-negative' : ''} />
    </div>
    <div className="dashboard-matrix-cell" role="gridcell" data-section="库存库龄">
      <AgingGrid keys={SLOW_MOVING_GROUPS.stock} row={row} format={format} />
    </div>
    <div className="dashboard-matrix-cell" role="gridcell" data-section="资金库龄">
      <AgingGrid keys={SLOW_MOVING_GROUPS.capital} row={row} format={format} />
    </div>
  </div>;
}

export function DashboardDecisionMatrix({
  kind,
  section,
}: {
  kind: DashboardMatrixKind;
  section: DashboardSection;
}) {
  const format = createFormatter(section.columns);
  const headers = kind === 'product-detail'
    ? PRODUCT_HEADERS
    : kind === 'low-margin'
      ? LOW_MARGIN_HEADERS
      : SLOW_MOVING_HEADERS;
  return <div
    className={`dashboard-decision-matrix dashboard-decision-matrix-${kind}`}
    role="grid"
    aria-label={`${section.title}决策矩阵`}
    aria-colcount={headers.length}
    aria-rowcount={(section.total || section.rows.length) + 1}
  >
    <MatrixHeader labels={headers} kind={kind} />
    <div className="dashboard-matrix-body">
      {section.rows.map((row, index) => kind === 'product-detail'
        ? <ProductRow key={`${String(row.SKU)}-${String(row.ASIN)}-${index}`} row={row} index={index} format={format} />
        : kind === 'low-margin'
          ? <LowMarginRow key={`${String(row.SKU)}-${String(row.ASIN)}-${String(row['国家'])}-${index}`} row={row} index={index} format={format} />
          : <SlowMovingRow key={`${String(row.SKU)}-${String(row.ASIN)}-${index}`} row={row} index={index} format={format} />)}
    </div>
  </div>;
}
