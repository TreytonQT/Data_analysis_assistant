import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, Badge, Button, ConfigProvider, Drawer, Layout, Menu, Space, Spin, Switch, Typography, theme } from 'antd';
import { BellOutlined, DashboardOutlined, DeploymentUnitOutlined, FileAddOutlined, FundOutlined, InboxOutlined, MoonOutlined, SettingOutlined, SunOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { api, type AppRevisions } from './api';
import './styles.css';

const UploadCenter = lazy(() => import('./UploadCenter'));
const ConfigCenter = lazy(() => import('./ConfigCenter'));
const DashboardPage = lazy(() => import('./DashboardPage'));
const ReplenishmentPage = lazy(() => import('./ReplenishmentPage'));
const BatchMonitorPage = lazy(() => import('./BatchMonitorPage'));
const SlowMovingPage = lazy(() => import('./SlowMovingPage'));
const TaskBoard = lazy(() => import('./TaskBoard'));

const { Header, Content, Sider } = Layout;
type PageKey = 'overview' | 'sales' | 'slow-moving' | 'products' | 'department' | 'replenishment' | 'batch-monitor' | 'uploads' | 'config';
const nav: Array<{ key: PageKey; icon: ReactNode; label: string }> = [
  { key: 'overview', icon: <DashboardOutlined />, label: '经营首页' }, { key: 'sales', icon: <FundOutlined />, label: '销量看板' }, { key: 'slow-moving', icon: <InboxOutlined />, label: '滞销提醒' }, { key: 'products', icon: <UnorderedListOutlined />, label: '产品管理' }, { key: 'department', icon: <FundOutlined />, label: '部门监控' }, { key: 'replenishment', icon: <FileAddOutlined />, label: '补货管理' }, { key: 'batch-monitor', icon: <DeploymentUnitOutlined />, label: '批次监控' }, { key: 'uploads', icon: <FileAddOutlined />, label: '上传中心' }, { key: 'config', icon: <SettingOutlined />, label: '配置中心' },
];
type RevisionDomain = keyof AppRevisions;

const navKeys = new Set<string>(nav.map(item => item.key));
const pageRevisionDomains: Record<PageKey, RevisionDomain[]> = {
  overview: ['dashboard'], sales: ['dashboard'], products: ['dashboard'], department: ['dashboard'], replenishment: ['dashboard'],
  'slow-moving': ['dashboard', 'promotions'], 'batch-monitor': ['batch_monitor'], uploads: ['reports'], config: ['configs'],
};
const routeChangeEvent = 'sales-dashboard-route-change';

function pageFromUrl(): PageKey {
  const requested = new URLSearchParams(window.location.search).get('page') || 'overview';
  return navKeys.has(requested) ? requested as PageKey : 'overview';
}

function defaultSearch(page: PageKey) {
  const params = new URLSearchParams();
  params.set('page', page);
  return `?${params.toString()}`;
}

function RouteLoading({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? 'drawer-route-loading' : 'route-loading'}><Spin size="large" tip="正在加载页面…" /></div>;
}

function App() {
  const initialPage = useRef(pageFromUrl()).current;
  const [page, setPage] = useState<PageKey>(initialPage);
  const [mountedPages, setMountedPages] = useState<Set<PageKey>>(() => new Set([initialPage]));
  const [domainRefreshVersions, setDomainRefreshVersions] = useState<Record<RevisionDomain, number>>({ dashboard: 0, promotions: 0, reports: 0, configs: 0, batch_monitor: 0 });
  const [pageRouteVersions, setPageRouteVersions] = useState<Record<PageKey, number>>(() => Object.fromEntries(nav.map(item => [item.key, 0])) as Record<PageKey, number>);
  const [dark, setDark] = useState(() => localStorage.getItem('dashboard-theme') === 'dark');
  const [notices, setNotices] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const activePageRef = useRef(page);
  const routeSearches = useRef<Partial<Record<PageKey, string>>>({ [initialPage]: window.location.search || defaultSearch(initialPage) });
  const lastSearch = useRef(window.location.search || defaultSearch(initialPage));
  const seenPageRevisions = useRef<Partial<Record<PageKey, Pick<AppRevisions, RevisionDomain>>>>({});
  const activationRequest = useRef(0);

  useEffect(() => { activePageRef.current = page; }, [page]);

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
      // Version checks must never prevent local navigation. The page can still use its own refresh action.
      return [] as RevisionDomain[];
    }
  }, []);

  const activatePage = useCallback(async (target: PageKey, targetSearch: string, historyMode: 'push' | 'none') => {
    const requestId = ++activationRequest.current;
    const changedDomains = await comparePageRevision(target);
    if (requestId !== activationRequest.current) return;
    if (historyMode === 'push') window.history.pushState({}, '', targetSearch);
    routeSearches.current[target] = targetSearch;
    lastSearch.current = targetSearch;
    setMountedPages(current => current.has(target) ? current : new Set([...current, target]));
    if (changedDomains.length) setDomainRefreshVersions(current => {
      const next = { ...current };
      changedDomains.forEach(domain => { next[domain] += 1; });
      return next;
    });
    setPage(target);
  }, [comparePageRevision]);

  const navigate = (target: PageKey) => {
    const current = activePageRef.current;
    routeSearches.current[current] = window.location.search || defaultSearch(current);
    const nextSearch = routeSearches.current[target] || defaultSearch(target);
    if (target === current) {
      void activatePage(target, nextSearch, 'none');
      return;
    }
    void activatePage(target, nextSearch, 'push');
  };

  useEffect(() => {
    void comparePageRevision(initialPage);
  }, [comparePageRevision, initialPage]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = pageFromUrl();
      routeSearches.current[next] = window.location.search || defaultSearch(next);
      lastSearch.current = window.location.search || defaultSearch(next);
    };
    const onPopState = () => {
      const current = activePageRef.current;
      routeSearches.current[current] = lastSearch.current;
      const target = pageFromUrl();
      const targetSearch = window.location.search || defaultSearch(target);
      setPageRouteVersions(current => ({ ...current, [target]: current[target] + 1 }));
      void activatePage(target, targetSearch, 'none');
    };
    window.addEventListener(routeChangeEvent, onRouteChange);
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener(routeChangeEvent, onRouteChange);
      window.removeEventListener('popstate', onPopState);
    };
  }, [activatePage]);

  const renderPage = (key: PageKey) => {
    const active = page === key;
    const dashboardRefreshVersion = domainRefreshVersions.dashboard;
    const content = key === 'uploads'
      ? <UploadCenter active={active} refreshVersion={domainRefreshVersions.reports} />
      : key === 'config'
        ? <ConfigCenter active={active} refreshVersion={domainRefreshVersions.configs} />
        : key === 'slow-moving'
          ? <SlowMovingPage active={active} routeVersion={pageRouteVersions[key]} dashboardRefreshVersion={dashboardRefreshVersion} promotionsRefreshVersion={domainRefreshVersions.promotions} />
          : key === 'replenishment'
            ? <ReplenishmentPage active={active} routeVersion={pageRouteVersions[key]} refreshVersion={dashboardRefreshVersion} />
            : key === 'batch-monitor'
              ? <BatchMonitorPage active={active} routeVersion={pageRouteVersions[key]} refreshVersion={domainRefreshVersions.batch_monitor} />
          : <DashboardPage page={key} active={active} routeVersion={pageRouteVersions[key]} refreshVersion={dashboardRefreshVersion} />;
    return <section key={key} className={`route-pane${active ? ' route-pane-active' : ''}`} aria-hidden={!active}>
      <div className="content"><Suspense fallback={<RouteLoading />}>{content}</Suspense></div>
    </section>;
  };

  return <ConfigProvider theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm, token: { colorPrimary: '#3b82f6', borderRadius: 10, fontFamily: 'Inter, Microsoft YaHei, sans-serif', colorBgBase: dark ? '#08111f' : '#ffffff', colorBgContainer: dark ? '#142238' : '#ffffff', colorBgElevated: dark ? '#16263d' : '#ffffff', colorText: dark ? '#edf4ff' : '#172033', colorTextSecondary: dark ? '#a9b9cf' : '#667085', colorBorder: dark ? '#2d4059' : '#e0e7f0' } }}>
    <AntApp>
      <Layout className={`app-shell ${dark ? 'dark-mode' : ''}`}>
        <Sider width={240} breakpoint="lg" collapsedWidth="0" className="side-nav">
          <div className="brand"><div className="brand-mark">数</div><div><strong>销售数据看板</strong><span>经营分析工作台</span></div></div>
          <Menu theme={dark ? 'dark' : 'light'} mode="inline" selectedKeys={[page]} items={nav} onClick={({ key }) => navigate(key as PageKey)} />
        </Sider>
        <Layout className="main-layout">
          <Header className="topbar"><Typography.Text strong>{nav.find(item => item.key === page)?.label || '销售数据看板'}</Typography.Text><Space><Switch checked={dark} onChange={value => { setDark(value); localStorage.setItem('dashboard-theme', value ? 'dark' : 'light'); }} checkedChildren={<MoonOutlined />} unCheckedChildren={<SunOutlined />} /><Badge count={notices} size="small"><Button icon={<BellOutlined />} onClick={() => setDrawer(true)}>提醒</Button></Badge></Space></Header>
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

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
