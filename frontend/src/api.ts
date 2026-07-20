export type Status = 'todo' | 'current' | 'in_progress' | 'snoozed' | 'completed';
export type Recurrence = 'none' | 'daily' | 'weekly' | 'monthly';
export interface Task { id: string; title: string; notes: string; status: Status; due_at?: string | null; remind_at?: string | null; next_reminder_at?: string | null; recurrence_type: Recurrence; recurrence_days: number[]; created_at: string; updated_at: string; sort_order: number; is_overdue: boolean; }
export interface TaskInput { title: string; notes: string; status: Status; due_at?: string | null; remind_at?: string | null; recurrence_type: Recurrence; recurrence_days: number[]; }
export interface SourceRecord { [key: string]: unknown }
export interface ReportsResponse { reports: SourceRecord[]; sources: Record<string, { title: string; records: SourceRecord[] }> }
export interface ConfigData { name: string; title: string; description: string; columns: string[]; rows: Record<string, unknown>[]; updated_at?: string | null }
export interface DashboardMetric { name: string; value: unknown; format?: string; unit?: string; precision?: number }
export interface DashboardColumn {
  key: string;
  label: string;
  type?: string;
  format?: string;
  unit?: string;
  precision?: number;
  sortable?: boolean;
}
export interface DashboardChartSeries {
  key: string;
  label?: string;
  type?: string;
  format?: string;
  unit?: string;
  precision?: number;
}
export interface DashboardChart {
  kind?: string;
  x: string;
  series: DashboardChartSeries[];
}
export interface DashboardSection {
  key: string;
  title: string;
  columns: DashboardColumn[];
  rows: Record<string, unknown>[];
  chart?: DashboardChart | null;
  page?: number;
  page_size?: number;
  total?: number;
  paginated?: boolean;
  server_managed?: boolean;
}
export interface DashboardPayload { title: string; has_data: boolean; message?: string | null; warnings?: string[]; filters: Record<string, string[]>; selected: Record<string, string | string[] | null>; metrics: DashboardMetric[]; sections: DashboardSection[]; updated_at?: number | string }

export type PromotionStatus = 'pending' | 'active' | 'ended';
export type PromotionStatusFilter = PromotionStatus | 'all';
export type PromotionDiscount = 5 | 8 | 10;
export interface PromotionCandidate {
  sku: string;
  asin?: string | null;
  developer?: string | null;
  available_inventory: number;
  sales_90d: number;
  aged_inventory_90d: number;
  average_7d: number;
  average_30d: number;
  daily_lift: number;
  discount_percent: PromotionDiscount;
  rule_key: string;
}
export interface PromotionRecord extends PromotionCandidate {
  id: string;
  asin_snapshot?: string | null;
  developer_snapshot?: string | null;
  start_date: string;
  end_date?: string | null;
  status: PromotionStatus;
  source_missing: boolean;
  created_at: string;
  updated_at: string;
}
export interface PromotionDiscountSummary {
  discount_percent: PromotionDiscount;
  sku_count: number;
  average_7d: number;
  average_30d: number;
  daily_lift: number;
}
export interface PromotionOverview {
  active_sku_count: number;
  average_7d_total: number;
  average_30d_total: number;
  daily_lift_total: number;
  daily_lift_average: number;
  by_discount: PromotionDiscountSummary[];
  source_missing_count?: number;
  developers?: string[];
  selected_developers?: string[];
  updated_at?: number | string | null;
}
export interface PromotionPage<T> {
  columns: DashboardColumn[];
  rows: T[];
  page: number;
  page_size: number;
  total: number;
  developers?: string[];
}
export interface PromotionListParams {
  page?: number;
  page_size?: number;
  search?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  developers?: string;
}
export interface PromotionDateInput { start_date: string; end_date: string | null }

export function apiErrorMessage(payload: unknown, fallback = '请求失败') {
  const response = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const detail = response.detail ?? payload;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const structured = detail as Record<string, unknown>;
    const message = typeof structured.message === 'string' && structured.message ? structured.message : fallback;
    const count = Number.isFinite(Number(structured.count)) ? `（${Number(structured.count)} 条）` : '';
    const examples = Array.isArray(structured.examples) && structured.examples.length
      ? `；示例：${structured.examples.slice(0, 3).map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('、')}`
      : '';
    return `${message}${count}${examples}`;
  }
  return fallback;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }, ...init });
  if (!response.ok) throw new Error(apiErrorMessage(await response.json().catch(() => null)));
  return response.status === 204 ? (undefined as T) : response.json();
}

async function requestText(url: string, init?: RequestInit): Promise<string> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json().catch(() => null) : await response.text().catch(() => '');
    throw new Error(apiErrorMessage(payload));
  }
  return response.text();
}

function queryString(params?: Record<string, string | number | undefined>) {
  if (!params) return '';
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const result = query.toString();
  return result ? `?${result}` : '';
}

function inferredColumn(key: string): DashboardColumn {
  const percent = /(毛利率|毛利率目标|占比|费用率|提点|完成率|目标毛利率)$/.test(key);
  const amount = !percent && /(销售额|营业额|毛利|利润|广告费|成本|货值|提成|计提|弃置费|占用资金|金额|费用|收入|支出)/.test(key);
  const integer = /(数量|库存|订单|销量|产品数|SKU数|ASIN数|在售个数)$/.test(key);
  return { key, label: key, type: percent ? 'percent' : amount || integer ? 'number' : 'string', format: percent ? 'percent' : amount ? 'amount' : integer ? 'integer' : undefined, sortable: true };
}

function normalizeColumn(column: string | DashboardColumn): DashboardColumn {
  return typeof column === 'string' ? inferredColumn(column) : { ...inferredColumn(column.key), ...column, label: column.label || column.key };
}

function normalizeChart(chart: unknown): DashboardChart | null {
  if (!chart || typeof chart !== 'object') return null;
  const value = chart as { kind?: string; x?: string; y?: string; series?: Array<string | DashboardChartSeries> };
  if (!value.x) return null;
  const rawSeries = value.series?.length ? value.series : value.y ? [{ key: value.y }] : [];
  const series: DashboardChartSeries[] = rawSeries.map(item => {
    const seriesValue: DashboardChartSeries = typeof item === 'string' ? { key: item, label: item } : item;
    const inferred = inferredColumn(seriesValue.key);
    return {
      key: seriesValue.key,
      label: seriesValue.label || seriesValue.key,
      type: seriesValue.type,
      format: seriesValue.format ?? inferred.format,
      unit: seriesValue.unit ?? inferred.unit,
      precision: seriesValue.precision ?? inferred.precision,
    };
  });
  return series.length ? { kind: value.kind, x: value.x, series } : null;
}

export function normalizeDashboardSection(section: unknown): DashboardSection {
  const value = (section || {}) as Record<string, unknown>;
  const rows = Array.isArray(value.rows) ? value.rows as Record<string, unknown>[] : [];
  const rawColumns = Array.isArray(value.columns) ? value.columns as Array<string | DashboardColumn> : Object.keys(rows[0] || {});
  const serverManaged = ['page', 'page_size', 'total', 'paginated'].every(key => Object.prototype.hasOwnProperty.call(value, key));
  return {
    key: String(value.key || ''),
    title: String(value.title || value.key || ''),
    columns: rawColumns.map(normalizeColumn),
    rows,
    chart: normalizeChart(value.chart),
    page: Number(value.page) || 1,
    page_size: Number(value.page_size) || Math.max(rows.length, 1),
    total: Number.isFinite(Number(value.total)) ? Number(value.total) : rows.length,
    paginated: Boolean(value.paginated),
    server_managed: serverManaged,
  };
}

function normalizeDashboardPayload(payload: DashboardPayload): DashboardPayload {
  return { ...payload, filters: payload.filters || {}, selected: payload.selected || {}, metrics: payload.metrics || [], sections: (payload.sections || []).map(normalizeDashboardSection) };
}
export const api = {
  tasks: (search = '') => request<Task[]>(`/api/tasks${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  createTask: (payload: TaskInput) => request<Task>('/api/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  updateTask: (id: string, payload: TaskInput) => request<Task>(`/api/tasks/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  transition: (id: string, status: Status, remind_at?: string | null) => request<Task>(`/api/tasks/${id}/transition`, { method: 'POST', body: JSON.stringify({ status, remind_at }) }),
  moveTask: (id: string, status: Status, before_id: string | null) => request<Task>(`/api/tasks/${id}/move`, { method: 'POST', body: JSON.stringify({ status, before_id }) }),
  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: 'DELETE' }),
  importTasks: (tasks: TaskInput[]) => request<{ imported: number }>('/api/tasks/import', { method: 'POST', body: JSON.stringify(tasks) }),
  notifications: () => request<Task[]>('/api/notifications'),
  dashboard: async (page: string, params?: Record<string, string>, signal?: AbortSignal) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : '';
    return normalizeDashboardPayload(await request<DashboardPayload>(`/api/dashboard/${page}${query}`, { signal }));
  },
  dashboardSection: async (page: string, section: string, params?: Record<string, string>, signal?: AbortSignal) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : '';
    return normalizeDashboardSection(await request<DashboardSection>(`/api/dashboard/${encodeURIComponent(page)}/sections/${encodeURIComponent(section)}${query}`, { signal }));
  },
  reports: () => request<ReportsResponse>('/api/reports'),
  deleteReport: (month: string) => request<{ ok: boolean }>(`/api/reports/performance/${encodeURIComponent(month)}`, { method: 'DELETE' }),
  deleteSource: (key: string) => request<{ ok: boolean }>(`/api/reports/source/${key}`, { method: 'DELETE' }),
  previewSource: (key: string) => request<{ title: string; columns: string[]; rows: Record<string, unknown>[]; total: number }>(`/api/reports/source/${key}/preview`),
  configs: () => request<{ configs: ConfigData[] }>('/api/configs'),
  saveConfig: (name: string, rows: Record<string, unknown>[]) => request<{ ok: boolean; rows: Record<string, unknown>[]; updated_at?: string | null }>(`/api/config/${name}`, { method: 'PUT', body: JSON.stringify(rows) }),
  promotionOverview: (signal?: AbortSignal) => request<PromotionOverview>('/api/promotions/overview', { signal }),
  promotionCandidates: (discount: PromotionDiscount, params?: PromotionListParams, signal?: AbortSignal) =>
    request<PromotionPage<PromotionCandidate>>(`/api/promotions/candidates/${discount}${queryString(params as Record<string, string | number | undefined>)}`, { signal }),
  promotionCandidateSkus: (discount: PromotionDiscount, params?: Pick<PromotionListParams, 'search' | 'developers' | 'sort_by' | 'sort_order'>) =>
    requestText(`/api/promotions/candidates/${discount}/skus.txt${queryString(params as Record<string, string | number | undefined>)}`),
  promotionRecords: (params?: PromotionListParams & { status?: PromotionStatusFilter }, signal?: AbortSignal) =>
    request<PromotionPage<PromotionRecord>>(`/api/promotions/records${queryString(params as Record<string, string | number | undefined>)}`, { signal }),
  createPromotions: (skus: string[], values: PromotionDateInput) =>
    request<{ created: PromotionRecord[] }>('/api/promotions', { method: 'POST', body: JSON.stringify({ skus, ...values }) }),
  updatePromotion: (id: string, values: PromotionDateInput) =>
    request<PromotionRecord>(`/api/promotions/${id}`, { method: 'PUT', body: JSON.stringify(values) }),
  deletePromotion: (id: string) => request<void>(`/api/promotions/${id}`, { method: 'DELETE' }),
};
