import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, Badge, Button, ConfigProvider, Drawer, Layout, Menu, Space, Spin, Switch, Typography, theme } from 'antd';
import { BellOutlined, DashboardOutlined, FileAddOutlined, FundOutlined, InboxOutlined, MoonOutlined, SettingOutlined, SunOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { api } from './api';
import './styles.css';

const UploadCenter = lazy(() => import('./UploadCenter'));
const ConfigCenter = lazy(() => import('./ConfigCenter'));
const DashboardPage = lazy(() => import('./DashboardPage'));
const SlowMovingPage = lazy(() => import('./SlowMovingPage'));
const TaskBoard = lazy(() => import('./TaskBoard'));

const { Header, Content, Sider } = Layout;
const nav = [
  { key: 'overview', icon: <DashboardOutlined />, label: '经营首页' }, { key: 'sales', icon: <FundOutlined />, label: '销量看板' }, { key: 'slow-moving', icon: <InboxOutlined />, label: '滞销提醒' }, { key: 'products', icon: <UnorderedListOutlined />, label: '产品管理' }, { key: 'department', icon: <FundOutlined />, label: '部门监控' }, { key: 'replenishment', icon: <FileAddOutlined />, label: '补货管理' }, { key: 'uploads', icon: <FileAddOutlined />, label: '上传中心' }, { key: 'config', icon: <SettingOutlined />, label: '配置中心' },
];
const navKeys = new Set(nav.map(item => item.key));

function pageFromUrl() {
  const requested = new URLSearchParams(window.location.search).get('page') || 'overview';
  return navKeys.has(requested) ? requested : 'overview';
}

function RouteLoading({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? 'drawer-route-loading' : 'route-loading'}><Spin size="large" tip="正在加载页面…" /></div>;
}

function App() {
  const [page, setPage] = useState(pageFromUrl);
  const [dark, setDark] = useState(() => localStorage.getItem('dashboard-theme') === 'dark');
  const [notices, setNotices] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const refreshNotices = useCallback(async () => {
    try { const rows = await api.notifications(); setNotices(rows.length); } catch { /* 保留上一次成功的角标，等待下次轮询。 */ }
  }, []);
  useEffect(() => {
    void refreshNotices();
    const timer = window.setInterval(() => { void refreshNotices(); }, 60000);
    return () => clearInterval(timer);
  }, [refreshNotices]);
  useEffect(() => {
    const onPopState = () => setPage(pageFromUrl());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  const navigate = (nextPage: string) => {
    if (nextPage === page) return;
    const url = new URL(window.location.href);
    url.search = '';
    url.searchParams.set('page', nextPage);
    window.history.pushState({}, '', url);
    setPage(nextPage);
  };
  const current = page === 'uploads' ? <UploadCenter /> : page === 'config' ? <ConfigCenter /> : page === 'slow-moving' ? <SlowMovingPage /> : <DashboardPage page={page} />;
  return <ConfigProvider theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm, token: { colorPrimary: '#3b82f6', borderRadius: 10, fontFamily: 'Inter, Microsoft YaHei, sans-serif', colorBgBase: dark ? '#08111f' : '#ffffff', colorBgContainer: dark ? '#142238' : '#ffffff', colorBgElevated: dark ? '#16263d' : '#ffffff', colorText: dark ? '#edf4ff' : '#172033', colorTextSecondary: dark ? '#a9b9cf' : '#667085', colorBorder: dark ? '#2d4059' : '#e0e7f0' } }}>
    <AntApp>
      <Layout className={`app-shell ${dark ? 'dark-mode' : ''}`}>
        <Sider width={240} breakpoint="lg" collapsedWidth="0" className="side-nav">
          <div className="brand"><div className="brand-mark">数</div><div><strong>销售数据看板</strong><span>经营分析工作台</span></div></div>
          <Menu theme={dark ? 'dark' : 'light'} mode="inline" selectedKeys={[page]} items={nav} onClick={({ key }) => navigate(key)} />
        </Sider>
        <Layout>
          <Header className="topbar"><Typography.Text strong>{nav.find(item => item.key === page)?.label || '销售数据看板'}</Typography.Text><Space><Switch checked={dark} onChange={value => { setDark(value); localStorage.setItem('dashboard-theme', value ? 'dark' : 'light'); }} checkedChildren={<MoonOutlined />} unCheckedChildren={<SunOutlined />} /><Badge count={notices} size="small"><Button icon={<BellOutlined />} onClick={() => setDrawer(true)}>提醒</Button></Badge></Space></Header>
          <Content className="content"><Suspense fallback={<RouteLoading />}>{current}</Suspense></Content>
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
