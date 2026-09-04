export type PageKey =
  | 'overview'
  | 'sales'
  | 'slow-moving'
  | 'products'
  | 'department'
  | 'replenishment'
  | 'batch-monitor'
  | 'uploads'
  | 'config';

export type RouteKey =
  | 'overview'
  | 'sales'
  | 'slow-moving:details'
  | 'slow-moving:promotion'
  | 'products:detail'
  | 'products:low-margin'
  | 'department:performance'
  | 'department:commission'
  | 'department:assessment'
  | 'replenishment'
  | 'batch-monitor'
  | 'uploads:daily'
  | 'uploads:weekly'
  | 'uploads:monthly'
  | 'config:metrics_config'
  | 'config:store_config'
  | 'config:monthly_targets'
  | 'config:department_fee_config'
  | 'config:commission_config'
  | 'config:replenishment_coverage_rules'
  | 'config:replenishment_switches'
  | 'config:replenishment_product_tags';

export type NavigationGroup = {
  kind: 'group';
  key: string;
  label: string;
  parentKeys: string[];
  children: NavigationNode[];
};

export type NavigationLeaf = {
  kind: 'leaf';
  key: RouteKey;
  label: string;
  page: PageKey;
  parentKeys: string[];
  params: Record<string, string>;
  closable: boolean;
};

export type NavigationNode = NavigationGroup | NavigationLeaf;

export type QuickTabState = {
  key: RouteKey;
  label: string;
  search: string;
  closable: boolean;
};

const leaf = (
  key: RouteKey,
  label: string,
  page: PageKey,
  parentKeys: string[] = [],
  params: Record<string, string> = {},
): NavigationLeaf => ({ kind: 'leaf', key, label, page, parentKeys, params, closable: key !== 'overview' });

const group = (key: string, label: string, children: NavigationNode[], parentKeys: string[] = []): NavigationGroup => ({
  kind: 'group', key, label, parentKeys, children,
});

export const navigationTree: NavigationNode[] = [
  leaf('overview', '经营首页', 'overview'),
  leaf('sales', '销量看板', 'sales'),
  group('slow-moving', '滞销提醒', [
    leaf('slow-moving:details', '滞销明细', 'slow-moving', ['slow-moving'], { tab: 'details' }),
    leaf('slow-moving:promotion', '促销提醒', 'slow-moving', ['slow-moving'], { tab: 'promotion' }),
  ]),
  group('products', '产品管理', [
    leaf('products:detail', '产品管理明细', 'products', ['products'], { tab: 'detail' }),
    leaf('products:low-margin', '低毛利率 SKU', 'products', ['products'], { tab: 'low-margin' }),
  ]),
  group('department', '部门监控', [
    leaf('department:performance', '业绩监控', 'department', ['department'], { tab: 'performance' }),
    leaf('department:commission', '提成监控', 'department', ['department'], { tab: 'commission' }),
    leaf('department:assessment', '考核监控', 'department', ['department'], { tab: 'assessment' }),
  ]),
  leaf('replenishment', '补货管理', 'replenishment'),
  leaf('batch-monitor', '批次监控', 'batch-monitor'),
  group('uploads', '上传中心', [
    leaf('uploads:daily', '每日上传', 'uploads', ['uploads'], { tab: 'daily' }),
    leaf('uploads:weekly', '每周上传', 'uploads', ['uploads'], { tab: 'weekly' }),
    leaf('uploads:monthly', '每月上传', 'uploads', ['uploads'], { tab: 'monthly' }),
  ]),
  group('config', '配置中心', [
    leaf('config:metrics_config', '指标公式配置', 'config', ['config'], { config_tab: 'metrics_config' }),
    leaf('config:store_config', '店铺配置', 'config', ['config'], { config_tab: 'store_config' }),
    leaf('config:monthly_targets', '目标配置', 'config', ['config'], { config_tab: 'monthly_targets' }),
    leaf('config:department_fee_config', '部门费用率', 'config', ['config'], { config_tab: 'department_fee_config' }),
    leaf('config:commission_config', '提成配置', 'config', ['config'], { config_tab: 'commission_config' }),
    leaf('config:replenishment_coverage_rules', '库存覆盖规则', 'config', ['config'], { config_tab: 'replenishment_coverage_rules' }),
    leaf('config:replenishment_switches', '补货开关', 'config', ['config'], { config_tab: 'replenishment_switches' }),
    leaf('config:replenishment_product_tags', 'ASIN产品标签', 'config', ['config'], { config_tab: 'replenishment_product_tags' }),
  ]),
];

function flattenLeaves(node: NavigationNode): NavigationLeaf[] {
  return node.kind === 'leaf' ? [node] : node.children.flatMap(flattenLeaves);
}

function flattenGroups(node: NavigationNode): NavigationGroup[] {
  return node.kind === 'leaf' ? [] : [node, ...node.children.flatMap(flattenGroups)];
}

export const navigationLeaves = navigationTree.flatMap(flattenLeaves);
export const navigationLeafByKey = new Map<RouteKey, NavigationLeaf>(navigationLeaves.map(item => [item.key, item]));
export const navigationGroupByKey = new Map<string, NavigationGroup>(navigationTree.flatMap(flattenGroups).map(item => [item.key, item]));

export function pageForRoute(key: RouteKey): PageKey {
  return navigationLeafByKey.get(key)?.page || 'overview';
}

export function routeLeafForSearch(search: string): NavigationLeaf {
  const params = new URLSearchParams(search);
  const page = params.get('page') as PageKey | null;
  if (page === 'slow-moving' && params.get('tab') === 'promotion') {
    return navigationLeafByKey.get('slow-moving:promotion')!;
  }
  if (page === 'config') {
    const configTab = params.get('config_tab');
    const key = `config:${configTab || 'metrics_config'}` as RouteKey;
    return navigationLeafByKey.get(key) || navigationLeafByKey.get('config:metrics_config')!;
  }
  const candidates = navigationLeaves.filter(item => item.page === page);
  if (candidates.length) {
    const matched = candidates.find(item => Object.entries(item.params).every(([name, value]) => params.get(name) === value));
    return matched || candidates[0];
  }
  return navigationLeafByKey.get('overview')!;
}

export function searchForRoute(key: RouteKey, currentSearch = '') {
  const route = navigationLeafByKey.get(key) || navigationLeafByKey.get('overview')!;
  const params = new URLSearchParams(currentSearch);
  const promotionView = route.key === 'slow-moving:promotion' && params.get('tab') === 'promotion' ? params.get('promotion_view') : null;
  params.set('page', route.page);
  ['tab', 'promotion_view', 'config_tab'].forEach(name => params.delete(name));
  Object.entries(route.params).forEach(([name, value]) => params.set(name, value));
  if (route.key === 'slow-moving:promotion' && promotionView) params.set('promotion_view', promotionView);
  return `?${params.toString()}`;
}

export function ancestorKeysForRoute(key: RouteKey) {
  return navigationLeafByKey.get(key)?.parentKeys || [];
}

export function topLevelLabelForRoute(key: RouteKey) {
  const route = navigationLeafByKey.get(key);
  if (!route) return '销售数据看板';
  const topLevel = navigationTree.find(item => item.key === route.parentKeys[0]) || navigationTree.find(item => item.kind === 'leaf' && item.key === key);
  return topLevel?.label || route.label;
}

export function validRouteKey(value: unknown): value is RouteKey {
  return typeof value === 'string' && navigationLeafByKey.has(value as RouteKey);
}
/** Resolve the active leaf from a browser query string, including legacy URLs. */
export const resolveRoute = routeLeafForSearch;

/** Build a canonical URL for a leaf while retaining page-local query state. */
export const buildRouteUrl = searchForRoute;

/** Navigate to a leaf and notify mounted pages that the route changed. */
export function navigateToRoute(key: RouteKey, currentSearch = '', mode: 'push' | 'replace' = 'push') {
  const nextSearch = searchForRoute(key, currentSearch);
  if (typeof window !== 'undefined') {
    window.history[mode === 'replace' ? 'replaceState' : 'pushState']({}, '', nextSearch);
    window.dispatchEvent(new Event('sales-dashboard-route-change'));
  }
  return nextSearch;
}
