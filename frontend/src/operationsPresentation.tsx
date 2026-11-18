import { Button, Tag, Tooltip, Typography } from 'antd';
import type { OperationsSku, OperationsSource, TrackingRow } from './api';
import SkuImagePreview from './SkuImagePreview';
import { formatAmountInWan } from './formatters';

export const quantity = (value: number | null | undefined, precision = 0) => value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: precision }).replace(/^-0$/, '0');
export const money = (value: number | null | undefined) => value == null ? '—' : formatAmountInWan(value) + ' 万';
export const rate = (value: number | null | undefined) => value == null ? '—' : (value * 100).toFixed(1) + '%';

export function SkuIdentity({ row, onOpen, country }: { row: Pick<OperationsSku, 'sku' | 'product_name' | 'image'>; onOpen: () => void; country?: string }) {
  return <div className="ops-identity"><SkuImagePreview image={row.image} alt={row.product_name || row.sku} className="ops-sku-image" placeholderClassName="ops-sku-image-placeholder" width={40} height={40} /><div>
    <Button type="text" className="ops-identity-link" onClick={onOpen} title={row.product_name || row.sku}>{row.product_name || row.sku}</Button>
    <span className="ops-identity-code" title={row.sku}>{row.sku}{country && <> · <b>{country}</b></>}</span>
  </div></div>;
}

export function RiskTags({ row }: { row: Pick<OperationsSku | TrackingRow, 'is_aged' | 'is_low_margin' | 'is_low_sales_new'> & { is_new?: boolean } }) {
  return <div className="ops-risk-tags">{row.is_aged && <Tag>库存积压</Tag>}{row.is_low_margin && <Tag>低毛利</Tag>}{row.is_low_sales_new ? <Tag>新品低销</Tag> : row.is_new ? <Tag>新品</Tag> : null}</div>;
}

export function AgingBar({ row }: { row: OperationsSku }) {
  const labels = ['91–180天', '181–330天', '331–365天', '366–455天', '456天以上'];
  const values = labels.map((_, i) => row[`age_stock_${i}`]);
  if (values.some(value => value == null)) return <Typography.Text type="secondary">库龄数据不完整</Typography.Text>;
  const total = values.reduce<number>((sum, value) => sum + (value || 0), 0);
  return <div className="ops-aging-bar" aria-label="90天以上库龄结构">{values.map((value, index) => value ? <Tooltip key={index} title={`${labels[index]}：${quantity(value)}件 · ${money(row[`age_capital_${index}`])}`}>
    <span tabIndex={0} className={`ops-aging-part ops-aging-part-${index}`} style={{ flex: value / total }} aria-label={`${labels[index]} ${quantity(value)}件`} />
  </Tooltip> : null)}</div>;
}

export function SourceDates({ sources, salesAsOf }: { sources?: Record<string, OperationsSource>; salesAsOf?: string | null }) {
  const short = (value?: string | null) => value ? value.slice(0, 10).replace(/^\d{4}-/, '') : '未知';
  const gross = sources?.gross_profit;
  return <Typography.Text type="secondary" className="ops-source-dates">库存 {sources?.operational_sales?.available ? short(sources.operational_sales.uploaded_at) : '未上传'} · 毛利 {gross?.available ? `${short(gross.start)}～${short(gross.end)}` : '未上传'} · 销量 {salesAsOf || sources?.sales_volume_detail?.available ? short(salesAsOf || sources?.sales_volume_detail?.end) : '未上传'}</Typography.Text>;
}
