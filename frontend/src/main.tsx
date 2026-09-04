import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, Badge, Button, ConfigProvider, Drawer, Layout, Menu, Space, Spin, Switch, Tabs, Typography, theme, type MenuProps } from 'antd';
import { BellOutlined, DashboardOutlined, DeploymentUnitOutlined, FileAddOutlined, FundOutlined, InboxOutlined, MoonOutlined, SettingOutlined, SunOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { api, type AppRevisions } from './api';
import './styles.css';
import { configureFeedback } from './feedback';
import SystemControls from './SystemControls';
import {
  ancestorKeysForRoute,
  navigationLeafByKey,
  navigationTree,
  pageForRoute,
  routeLeafForSearch,
  searchForRoute,
  topLevelLabelForRoute,
  validRouteKey,
  type NavigationNode,
  type PageKey,
  type QuickTabState,
  type RouteKey,
} from './navigation';
configureFeedback();

const UploadCenter = lazy(() => import('./UploadCenter'));
const ConfigCenter = lazy(() => import('./ConfigCenter'));
const DashboardPage = lazy(() => import('./DashboardPage'));
const ReplenishmentPage = lazy(() => import('./ReplenishmentPage'));
const BatchMonitorPage = lazy(() => import('./BatchMonitorPage'));
const SlowMovingPage = lazy(() => import('./SlowMovingPage'));
const TaskBoard = lazy(() => import('./TaskBoard'));

const { Header, Content, Sider } = Layout;
type RevisionDomain = keyof AppRevisions;
const pageKeys: PageKey[] = ['overview', 'sales', 'slow-moving', 'products', 'department', 'replenishment', 'batch-monitor', 'uploads', 'config'];
const routeChangeEvent = 'sales-dashboard-route-change';
const quickTabsStorageKey = 'sales-dashboard-quick-tabs-v1';
const iconByKey: Record<string, ReactNode> = {
  overview: <DashboardOutlined />, sales: <FundOutlined />, 'slow-moving': <InboxOutlined />, products: <UnorderedListOutlined />,
  department: <FundOutlined />, replenishment: <FileAddOutlined />, 'batch-monitor': <DeploymentUnitOutlined />, uploads: <FileAddOutlined />, config: <SettingOutlined />,
};

const pageRevisionDomains: Record<PageKey, RevisionDomain[]> = {
  overview: ['dashboard'], sales: ['dashboard'], products: ['dashboard', 'batch_monitor', 'promotions'], department: ['dashboard'], replenishment: ['dashboard'],
  'slow-moving': ['dashboard', 'promotions'], 'batch-monitor': ['batch_monitor'], uploads: ['reports'], config: ['configs'],
};

function menuItems(nodes: NavigationNode[]): NonNullable<MenuProps['items']> {
  return nodes.map(node => node.kind === 'group'
    ? { key: node.key, icon: iconByKey[node.key], label: node.label, children: menuItems(node.children) }
    : { key: node.key, icon: node.parentKeys.length ? undefined : iconByKey[node.page], label: node.label });
}

const sidebarItems = menuItems(navigationTree);

function quickTabForRoute(key: RouteKey, search: string): QuickTabState {
  const route = navigationLeafByKey.get(key)!;
  return { key, label: route.label, search, closable: route.closable };
}

function readQuickTabs(initialKey: RouteKey, initialSearch: string): QuickTabState[] {
  const home = quickTabForRoute('overview', searchForRoute('overview'));
  const result: QuickTabState[] = [home];
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(quickTabsStorageKey) || '[]') as unknown;
    if (Array.isArray(stored)) {
      stored.forEach(item => {
        if (!item || typeof item !== 'object') return;
        const key = (item as { key?: unknown }).key;
        if (!validRouteKey(key) || key === 'overview' || result.some(tab => tab.key === key)) return;
        const search = typeof (item as { search?: unknown }).search === 'string'
          ? searchForRoute(key, (item as { search: string }).search)
          : searchForRoute(key);
        result.push(quickTabForRoute(key, search));
      });
    }
  } catch {
    // A malformed session must never block navigation.
  }
  if (initialKey !== 'overview') {
    const existing = result.find(tab => tab.key === initialKey);
    if (existing) existing.search = initialSearch;
    else result.push(quickTabForRoute(initialKey, initialSearch));
  } else {
    result[0].search = initialSearch;
  }
  return result;
}

function persistQuickTabs(tabs: QuickTabState[]) {
  try {
    window.sessionStorage.setItem(quickTabsStorageKey, JSON.stringify(tabs));
  } catch {
    // Storage can be unavailable in privacy mode; in-memory tabs still work.
  }
}

function App() {
  const initialRoute = useRef(routeLeafForSearch(window.location.search)).current;
  const initialSearch = useRef(searchForRoute(initialRoute.key, window.location.search)).current;
  const [activeRouteKey, setActiveRouteKey] = useState<RouteKey>(initialRoute.key);
  const [mountedPages, setMountedPages] = useState<Set<PageKey>>(() => new Set([initialRoute.page]));
  const [domainRefreshVersions, setDomainRefreshVersions] = useState<Record<RevisionDomain, number>>({ dashboard: 0, promotions: 0, reports: 0, configs: 0, batch_monitor: 0 });
  const [pageRouteVersions, setPageRouteVersions] = useState<Record<PageKey, number>>(() => Object.fromEntries(pageKeys.map(key => [key, 0])) as Record<PageKey, number>);
  const [quickTabs, setQuickTabs] = useState<QuickTabState[]>(() => readQuickTabs(initialRoute.key, initialSearch));
  const [openKeys, setOpenKeys] = useState<string[]>(() => ancestorKeysForRoute(initialRoute.key));
  const [dark, setDark] = useState(() => localStorage.getItem('dashboard-theme') === 'dark');
  const [notices, setNotices] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const activeRouteRef = useRef(navigationLeafByKey.get(initialRoute.key)!);
  const routeSearches = useRef<Partial<Record<RouteKey, string>>>({ [initialRoute.key]: initialSearch });
  const seenPageRevisions = useRef<Partial<Record<PageKey, Pick<AppRevisions, RevisionDomain>>>>({});
  const activationRequest = useRef(0);

  useEffect(() => { activeRouteRef.current = navigationLeafByKey.get(activeRouteKey)!; }, [activeRouteKey]);
  useEffect(() => { persistQuickTabs(quickTabs); }, [quickTabs]);
  useEffect(() => {
    if (window.location.search !== initialSearch) window.history.replaceState({}, '', initialSearch);
  }, [initialSearch]);

  const refreshNotices = useCallback(async () => {
    try { const rows = await api.notifications(); setNotices(rows.length); } catch { /* 保留上一次成功的角标，等待下次轮询。 */ }
  }, []);
  useEffect(() => {
    void refreshNotices();
    const timer = window.setInterval(() => { void refreshNotices(); }, 60000);
    return () => clearInterval(timer);
  }, [refreshNotices]);

  const comparePageRevision = useCallback(async (target: PageKey) => {
    try {
      const current = await api.appRevisions();
      const domains = pageRevisionDomains[target];
      const previous = seenPageRevisions.current[target];
      const changedDomains = previous ? domains.filter(domain => previous[domain] !== current[domain]) : [];
      seenPageRevisions.current[target] = Object.fromEntries(domains.map(domain => [domain, current[domain]])) as Pick<AppRevisions, RevisionDomain>;
      return changedDomains;
    } catch {
      return [] as RevisionDomain[];
    }
  }, []);

  const activateRoute = useCallback(async (target: { key: RouteKey; page: PageKey; parentKeys: string[] }, targetSearch: string, historyMode: 'push' | 'none') => {
    const requestId = ++activationRequest.current;
    const changedDomains = await comparePageRevision(target.page);
    if (requestId !== activationRequest.current) return;
    if (historyMode === 'push') window.history.pushState({}, '', targetSearch);
    routeSearches.current[target.key] = targetSearch;
    setMountedPages(current => current.has(target.page) ? current : new Set([...current, target.page]));
    setPageRouteVersions(current => ({ ...current, [target.page]: current[target.page] + 1 }));
    setActiveRouteKey(target.key);
    setOpenKeys(current => Array.from(new Set([...current, ...target.parentKeys])));
    setQuickTabs(current => {
      const next = current.map(tab => tab.key === target.key ? { ...tab, search: targetSearch } : tab);
      return next.some(tab => tab.key === target.key) ? next : [...next, quickTabForRoute(target.key, targetSearch)];
    });
    if (changedDomains.length) setDomainRefreshVersions(current => {
      const next = { ...current };
      changedDomains.forEach(domain => { next[domain] += 1; });
      return next;
    });
  }, [comparePageRevision]);

  const navigateToRoute = useCallback((key: RouteKey) => {
    const target = navigationLeafByKey.get(key);
    if (!target) return;
    const current = activeRouteRef.current;
    const currentSearch = searchForRoute(current.key, window.location.search || routeSearches.current[current.key] || '');
    routeSearches.current[current.key] = currentSearch;
    const nextSearch = routeSearches.current[key] || searchForRoute(key);
    void activateRoute(target, nextSearch, key === current.key ? 'none' : 'push');
  }, [activateRoute]);

  useEffect(() => { void comparePageRevision(initialRoute.page); }, [comparePageRevision, initialRoute.page]);
  useEffect(() => {
    const onRouteChange = () => {
      const target = routeLeafForSearch(window.location.search);
      const targetSearch = searchForRoute(target.key, window.location.search);
      routeSearches.current[target.key] = targetSearch;
      if (target.key !== activeRouteRef.current.key) void activateRoute(target, targetSearch, 'none');
      else setQuickTabs(current => current.map(tab => tab.key === target.key ? { ...tab, search: targetSearch } : tab));
    };
    const onPopState = () => {
      const target = routeLeafForSearch(window.location.search);
      const targetSearch = searchForRoute(target.key, window.location.search);
      void activateRoute(target, targetSearch, 'none');
    };
    window.addEventListener(routeChangeEvent, onRouteChange);
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener(routeChangeEvent, onRouteChange);
      window.removeEventListener('popstate', onPopState);
    };
  }, [activateRoute]);

  const closeQuickTab = (key: string) => {
    if (!validRouteKey(key) || key === 'overview') return;
    const index = quickTabs.findIndex(tab => tab.key === key);
    if (index < 0) return;
    const fallback = quickTabs[index - 1] || quickTabs[index + 1] || quickTabs[0];
    setQuickTabs(current => current.filter(tab => tab.key !== key));
    if (activeRouteRef.current.key === key && fallback) navigateToRoute(fallback.key);
  };

  const renderPage = (key: PageKey) => {
    const active = pageForRoute(activeRouteKey) === key;
    const dashboardRefreshVersion = domainRefreshVersions.dashboard;
    const productRefreshVersion = dashboardRefreshVersion + domainRefreshVersions.batch_monitor;
    const content = key === 'uploads'
      ? <UploadCenter active={active} routeVersion={pageRouteVersions[key]} refreshVersion={domainRefreshVersions.reports} />
      : key === 'config'
        ? <ConfigCenter active={active} routeVersion={pageRouteVersions[key]} refreshVersion={domainRefreshVersions.configs} />
        : key === 'slow-moving'
          ? <SlowMovingPage active={active} routeVersion={pageRouteVersions[key]} dashboardRefreshVersion={dashboardRefreshVersion} promotionsRefreshVersion={domainRefreshVersions.promotions} />
          : key === 'products'
            ? <DashboardPage page={key} active={active} routeVersion={pageRouteVersions[key]} refreshVersion={productRefreshVersion} />
          : key === 'replenishment'
            ? <ReplenishmentPage active={active} routeVersion={pageRouteVersions[key]} refreshVersion={dashboardRefreshVersion} />
            : key === 'batch-monitor'
              ? <BatchMonitorPage active={active} routeVersion={pageRouteVersions[key]} refreshVersion={domainRefreshVersions.batch_monitor} />
          : <DashboardPage page={key} active={active} routeVersion={pageRouteVersions[key]} refreshVersion={dashboardRefreshVersion} />;
    return <section key={key} className={`route-pane${active ? ' route-pane-active' : ''}`} aria-hidden={!active}>
      <div className="content"><Suspense fallback={<RouteLoading />}>{content}</Suspense></div>
    </section>;
  };

  const onMenuClick: MenuProps['onClick'] = ({ key }) => { if (validRouteKey(key)) navigateToRoute(key); };
  const onQuickTabEdit = (key: string | React.MouseEvent | React.KeyboardEvent, action: 'add' | 'remove') => { if (action === 'remove') closeQuickTab(String(key)); };

  return <ConfigProvider theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm, token: { colorPrimary: '#3b82f6', borderRadius: 10, fontFamily: 'Inter, Microsoft YaHei, sans-serif', colorBgBase: dark ? '#08111f' : '#ffffff', colorBgContainer: dark ? '#142238' : '#ffffff', colorBgElevated: dark ? '#16263d' : '#ffffff', colorText: dark ? '#edf4ff' : '#172033', colorTextSecondary: dark ? '#a9b9cf' : '#667085', colorBorder: dark ? '#2d4059' : '#e0e7f0' } }}>
    <AntApp message={{ top: 24, maxCount: 3, duration: 2.5 }}>
      <Layout className={`app-shell ${dark ? 'dark-mode' : ''}`}>
        <Sider width={240} collapsible collapsed={sidebarCollapsed} onCollapse={setSidebarCollapsed} breakpoint="lg" collapsedWidth={0} className="side-nav">
          <div className="brand"><div className="brand-mark">数</div><div><strong>销售数据看板</strong><span>经营分析工作台</span></div></div>
          <Menu theme={dark ? 'dark' : 'light'} mode="inline" selectedKeys={[activeRouteKey]} openKeys={openKeys} items={sidebarItems} onOpenChange={setOpenKeys} onClick={onMenuClick} />
        </Sider>
        <Layout className="main-layout">
          <Header className="topbar"><Typography.Text strong>{topLevelLabelForRoute(activeRouteKey)}</Typography.Text><Space><SystemControls /><Switch checked={dark} onChange={value => { setDark(value); localStorage.setItem('dashboard-theme', value ? 'dark' : 'light'); }} checkedChildren={<MoonOutlined />} unCheckedChildren={<SunOutlined />} /><Badge count={notices} size="small"><Button icon={<BellOutlined />} onClick={() => setDrawer(true)}>提醒</Button></Badge></Space></Header>
          <div className="quick-tabbar" aria-label="最近访问页面"><Tabs type="editable-card" hideAdd activeKey={activeRouteKey} items={quickTabs.map(tab => ({ key: tab.key, label: tab.label, closable: tab.closable, children: null }))} onChange={key => { if (validRouteKey(key)) navigateToRoute(key); }} onEdit={onQuickTabEdit} /></div>
          <Content className="content-viewport">{Array.from(mountedPages).map(renderPage)}</Content>
        </Layout>
      </Layout>
      <Drawer
        title={<Space><BellOutlined /><span>待办事项提醒</span>{notices > 0 && <Badge count={notices} size="small" />}</Space>}
        open={drawer}
        onClose={() => setDrawer(false)}
        width="min(1600px, 80vw)"
        rootClassName={`task-drawer ${dark ? 'dark-mode' : ''}`}
        styles={{ body: { padding: 0 } }}
        destroyOnHidden
      >
        <Suspense fallback={<RouteLoading compact />}><TaskBoard active={drawer} onTasksChanged={refreshNotices} /></Suspense>
      </Drawer>
    </AntApp>
  </ConfigProvider>;
}

function RouteLoading({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? 'drawer-route-loading' : 'route-loading'}><Spin size="large" tip="正在加载页面…" /></div>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
