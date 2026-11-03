/** Format a base-currency amount as ten-thousands; the caller supplies the unit label. */
export function formatAmountInWan(value: number) {
  return (value / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
