import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Spin } from 'antd';
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

  return <div className="slow-moving-page">
    {tab === 'details'
      ? <DashboardPage page="slow-moving" active={active} routeVersion={routeVersion} refreshVersion={dashboardRefreshVersion + promotionsRefreshVersion} />
      : <Suspense fallback={<PromotionLoading />}><PromotionBoard active={active} routeVersion={routeVersion} refreshVersion={promotionsRefreshVersion} /></Suspense>}
  </div>;
}
