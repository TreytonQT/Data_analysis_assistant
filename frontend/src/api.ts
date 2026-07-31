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
  summary?: Record<string, unknown> | null;
  group_rows?: ReplenishmentGroupRow[];
}
export interface ReplenishmentTag { label: string; color?: string }
export interface ReplenishmentCountryMetric { units: number | null; margin: number | null; reasons: string[] }
export interface ReplenishmentRating { review_count: number | null; score: number | null }
export interface ReplenishmentPromotion { start_date: unknown; end_date: unknown; discount_percent: number | null }
export interface ReplenishmentHistoryMonth {
  month: number;
  total_sales: number;
  active_days: number;
  nonzero_daily_average: number;
}
export interface ReplenishmentHistory {
  available: boolean;
  site_sales: Record<'DE' | 'FR' | 'ES' | 'IT', number>;
  peak_months: ReplenishmentHistoryMonth[];
  months?: ReplenishmentHistoryMonth[];
}
export interface ReplenishmentGroupRow {
  group_id: string;
  identity: {
    asin: string;
    original_sku: string;
    follower_skus: string[];
    sku_count: number;
    stores: string[];
    store_statuses: string[];
    developers: string[];
    tags: ReplenishmentTag[];
    rating: ReplenishmentRating | null;
  };
  countries: Record<'DE' | 'FR' | 'ES' | 'IT', ReplenishmentCountryMetric>;
  inventory: {
    amazon_available: number | null;
    group_total: number | null;
    asin_reference_total: number | null;
    aged_over_90: number | null;
    aged_180_to_365: number | null;
    aged_over_365: number | null;
    is_split_reference: boolean;
  };
  trend: {
    t_value: number | null;
    calibrated_daily_sales: number | null;
    max_weight_g: number | null;
    coverage_days: number | null;
  };
  promotion: ReplenishmentPromotion | null;
  history: ReplenishmentHistory;
  recommendation: {
    target_inventory: number | null;
    measured_quantity: number | null;
    official_quantity: number | null;
    enabled: boolean;
    close_reason: string | null;
    status: string | null;
    errors: string[];
  };
}
export interface DashboardPayload { title: string; has_data: boolean; message?: string | null; warnings?: string[]; filters: Record<string, string[]>; selected: Record<string, string | string[] | null>; metrics: DashboardMetric[]; sections: DashboardSection[]; group_rows?: ReplenishmentGroupRow[]; updated_at?: number | string }
export interface ReplenishmentGroupDetails {
  group: Record<string, unknown>;
  sku_columns: DashboardColumn[];
  sku_rows: Record<string, unknown>[];
  sales_history_2025: ReplenishmentHistory | null;
}
export interface ReplenishmentSwitchResult {
  ASIN: string;
  is_replenishment: boolean;
  close_reason: string;
  updated_at: string;
}
export interface AppRevisions { dashboard: string; promotions: string; reports: string; configs: string; batch_monitor: string }

export interface BatchMonitorMetrics {
  incomplete_batches: number;
  pending_artwork_batches: number;
  pending_shipment_skus: number;
  pending_arrival_skus: number;
}
export interface BatchMonitorRow {
  batch_no: string;
  artwork_completed_date: string | null;
  source_file_name: string;
  created_at: string;
  updated_at: string;
  sku_count: number;
  shipped_count: number;
  arrived_count: number;
  shipment_count: number;
  is_complete: boolean;
}
export interface BatchMonitorPayload {
  metrics: BatchMonitorMetrics;
  rows: BatchMonitorRow[];
  page: number;
  page_size: number;
  total: number;
  view: 'incomplete' | 'all' | 'completed';
  orphan_count: number;
  orphan_scope_available: boolean;
  orphan_scope_message: string;
  updated_at: string;
}
export interface BatchMonitorSku {
  sku: string;
  de_price: number | null;
  fr_price: number | null;
  es_price: number | null;
  it_price: number | null;
  asin: string | null;
  shipment_no: string | null;
  arrival_date: string | null;
}
export interface BatchMonitorDetails {
  batch: BatchMonitorRow;
  skus: BatchMonitorSku[];
}
export interface BatchShipmentUploadResult {
  rows: number;
  inserted: number;
  ignored: number;
  unassigned: number;
  conflicts: number;
  conflict_examples: Array<{
    sku: string;
    kept_shipment_no: string;
    ignored_shipment_no: string;
  }>;
}
export interface BatchCreateResult {
  batch_no: string;
  sheet: string;
  sku_count: number;
  source_sku_count: number;
  imported_sku_count: number;
  ignored_sku_count: number;
  ignored_examples: Array<{ sku: string; reason: string }>;
}
export interface BatchShipmentArrivalResult {
  shipment_no: string;
  arrival_date: string;
  updated: number;
  total: number;
  already_arrived: number;
  affected_batches: Array<{
    batch_no: string;
    updated_skus: number;
    arrived_count: number;
    sku_count: number;
    is_complete: boolean;
  }>;
}
export interface BatchOrphanPage {
  rows: Array<{
    sku: string;
    asin: string;
    shipment_no: string;
    arrival_date: string | null;
  }>;
  page: number;
  page_size: number;
  total: number;
}
export interface BatchCopyLists {
  unbound_shipment_skus: string[];
  pending_shipment_nos: string[];
  unbound_shipment_count: number;
  pending_shipment_count: number;
  updated_at: string;
}

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
export interface PromotionRecord extends Omit<PromotionCandidate, 'discount_percent'> {
  id: string;
  promotion_name: string;
  asin_snapshot?: string | null;
  developer_snapshot?: string | null;
  start_date: string;
  end_date?: string | null;
  status: PromotionStatus;
  source_missing: boolean;
  created_at: string;
  updated_at: string;
  discount_percent: number;
}
export interface LastPromotionRecord {
  sku: string;
  promotion_content: string;
  promotion_id: string;
  promotion_name: string;
  discount_percent: number;
  start_date: string;
  end_date?: string | null;
  updated_at: string;
}
export interface PromotionActivitySummary {
  promotion_name: string;
  discount_percents: number[];
  start_date: string;
  end_date?: string | null;
  status: PromotionStatus;
  sku_count: number;
  source_missing_count?: number;
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
  by_promotion: PromotionActivitySummary[];
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
export interface PromotionInput extends PromotionDateInput { promotion_name: string }
export interface ManualPromotionInput extends PromotionInput { discount_percent: number }

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

async function requestForm<T>(url: string, body: FormData): Promise<T> {
  const response = await fetch(url, { method: 'POST', body });
  if (!response.ok) throw new Error(apiErrorMessage(await response.json().catch(() => null)));
  return response.json();
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
    summary: value.summary && typeof value.summary === 'object' ? value.summary as Record<string, unknown> : null,
    group_rows: Array.isArray(value.group_rows) ? value.group_rows as ReplenishmentGroupRow[] : undefined,
  };
}

function normalizeDashboardPayload(payload: DashboardPayload): DashboardPayload {
  return {
    ...payload,
    filters: payload.filters || {},
    selected: payload.selected || {},
    metrics: payload.metrics || [],
    sections: (payload.sections || []).map(normalizeDashboardSection),
    group_rows: Array.isArray(payload.group_rows) ? payload.group_rows : undefined,
  };
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
  appRevisions: (signal?: AbortSignal) => request<AppRevisions>('/api/app-revisions', { signal }),
  dashboard: async (page: string, params?: Record<string, string>, signal?: AbortSignal) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : '';
    return normalizeDashboardPayload(await request<DashboardPayload>(`/api/dashboard/${page}${query}`, { signal }));
  },
  dashboardSection: async (page: string, section: string, params?: Record<string, string>, signal?: AbortSignal) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : '';
    return normalizeDashboardSection(await request<DashboardSection>(`/api/dashboard/${encodeURIComponent(page)}/sections/${encodeURIComponent(section)}${query}`, { signal }));
  },
  replenishmentGroupDetails: (groupId: string) => request<ReplenishmentGroupDetails>(`/api/dashboard/replenishment/groups/${encodeURIComponent(groupId)}/details`),
  updateReplenishmentSwitch: (asin: string, isReplenishment: boolean, closeReason: string) =>
    request<ReplenishmentSwitchResult>(`/api/dashboard/replenishment/asins/${encodeURIComponent(asin)}/switch`, {
      method: 'PUT',
      body: JSON.stringify({ is_replenishment: isReplenishment, close_reason: closeReason }),
    }),
  batchMonitor: (params?: { view?: string; search?: string; page?: number; page_size?: number }, signal?: AbortSignal) =>
    request<BatchMonitorPayload>(`/api/batch-monitor/batches${queryString(params)}`, { signal }),
  batchDetails: (batchNo: string, signal?: AbortSignal) =>
    request<BatchMonitorDetails>(`/api/batch-monitor/batches/${encodeURIComponent(batchNo)}`, { signal }),
  batchOrphans: (params?: { search?: string; page?: number; page_size?: number }, signal?: AbortSignal) =>
    request<BatchOrphanPage>(`/api/batch-monitor/orphans${queryString(params)}`, { signal }),
  batchCopyLists: (signal?: AbortSignal) =>
    request<BatchCopyLists>('/api/batch-monitor/copy-lists', { signal }),
  createBatch: (batchNo: string, file: File) => {
    const body = new FormData();
    body.append('batch_no', batchNo);
    body.append('file', file);
    return requestForm<BatchCreateResult>('/api/batch-monitor/batches', body);
  },
  uploadBatchShipments: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return requestForm<BatchShipmentUploadResult>('/api/batch-monitor/shipments', body);
  },
  updateBatchArtwork: (batchNo: string, completed: boolean) =>
    request<{ batch_no: string; completed: boolean; artwork_completed_date: string | null }>(
      `/api/batch-monitor/batches/${encodeURIComponent(batchNo)}/artwork`,
      { method: 'PUT', body: JSON.stringify({ completed }) },
    ),
  updateShipmentArrival: (shipmentNo: string, arrivalDate: string) =>
    request<BatchShipmentArrivalResult>(
      `/api/batch-monitor/shipments/${encodeURIComponent(shipmentNo)}/arrival`,
      { method: 'PUT', body: JSON.stringify({ arrival_date: arrivalDate }) },
    ),
  updateSkuArrival: (sku: string, arrived: boolean, arrivalDate?: string) =>
    request<{ sku: string; arrived: boolean; arrival_date: string | null }>(
      `/api/batch-monitor/skus/${encodeURIComponent(sku)}/arrival`,
      { method: 'PUT', body: JSON.stringify({ arrived, arrival_date: arrivalDate || null }) },
    ),
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
  lastPromotions: (params?: Omit<PromotionListParams, 'developers'>, signal?: AbortSignal) =>
    request<PromotionPage<LastPromotionRecord>>(`/api/promotions/last-promotions${queryString(params as Record<string, string | number | undefined>)}`, { signal }),
  createPromotions: (skus: string[], values: PromotionInput) =>
    request<{ created: PromotionRecord[] }>('/api/promotions', { method: 'POST', body: JSON.stringify({ skus, ...values }) }),
  createManualPromotions: (skus: string[], values: ManualPromotionInput) =>
    request<{ created: PromotionRecord[]; replaced: number }>('/api/promotions/manual', { method: 'POST', body: JSON.stringify({ skus, ...values }) }),
  updatePromotion: (id: string, values: PromotionInput) =>
    request<PromotionRecord>(`/api/promotions/${id}`, { method: 'PUT', body: JSON.stringify(values) }),
  deletePromotionActivity: (promotionName: string) =>
    request<{ deleted: number; promotion_name: string }>('/api/promotions/activities', { method: 'DELETE', body: JSON.stringify({ promotion_name: promotionName }) }),
  deletePromotion: (id: string) => request<void>(`/api/promotions/${id}`, { method: 'DELETE' }),
};
