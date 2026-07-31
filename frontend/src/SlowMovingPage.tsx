import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Spin, Tabs } from 'antd';
import DashboardPage from './DashboardPage';

const PromotionBoard = lazy(() => import('./PromotionBoard'));

export type SlowMovingTab = 'details' | 'promotion';

export function slowMovingTabFromSearch(search: string): SlowMovingTab {
  return new URLSearchParams(search).get('tab') === 'promotion' ? 'promotion' : 'details';
}

function PromotionLoading() {
  return <div className="route-loading"><Spin size="large" tip="正在加载促销提醒…" /></div>;
}

export default function SlowMovingPage({ active = true, routeVersion = 0, dashboardRefreshVersion = 0, promotionsRefreshVersion = 0 }: { active?: boolean; routeVersion?: number; dashboardRefreshVersion?: number; promotionsRefreshVersion?: number }) {
  const [tab, setTab] = useState<SlowMovingTab>(() => slowMovingTabFromSearch(window.location.search));
  const seenRouteVersion = useRef(routeVersion);

  useEffect(() => {
    const onPopState = () => { if (active) setTab(slowMovingTabFromSearch(window.location.search)); };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [active]);
  useEffect(() => {
    if (!active || seenRouteVersion.current === routeVersion) return;
    seenRouteVersion.current = routeVersion;
    setTab(slowMovingTabFromSearch(window.location.search));
  }, [active, routeVersion]);

  const changeTab = (value: string) => {
    const next = value as SlowMovingTab;
    if (next === tab) return;
    const url = new URL(window.location.href);
    url.searchParams.set('tab', next);
    window.history.pushState({}, '', url);
    window.dispatchEvent(new Event('sales-dashboard-route-change'));
    setTab(next);
  };

  return <div className="slow-moving-page">
    <Tabs className="slow-moving-tabs" activeKey={tab} onChange={changeTab} items={[{ key: 'details', label: '滞销明细' }, { key: 'promotion', label: '促销提醒' }]} />
    {tab === 'details'
      ? <DashboardPage page="slow-moving" active={active} routeVersion={routeVersion} refreshVersion={dashboardRefreshVersion} />
      : <Suspense fallback={<PromotionLoading />}><PromotionBoard active={active} routeVersion={routeVersion} refreshVersion={promotionsRefreshVersion} /></Suspense>}
  </div>;
}
