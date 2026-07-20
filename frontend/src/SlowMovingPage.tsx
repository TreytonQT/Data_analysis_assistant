import { lazy, Suspense, useEffect, useState } from 'react';
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

export default function SlowMovingPage() {
  const [tab, setTab] = useState<SlowMovingTab>(() => slowMovingTabFromSearch(window.location.search));

  useEffect(() => {
    const onPopState = () => setTab(slowMovingTabFromSearch(window.location.search));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const changeTab = (value: string) => {
    const next = value as SlowMovingTab;
    if (next === tab) return;
    const url = new URL(window.location.href);
    url.searchParams.set('tab', next);
    window.history.pushState({}, '', url);
    setTab(next);
  };

  return <div className="slow-moving-page">
    <Tabs className="slow-moving-tabs" activeKey={tab} onChange={changeTab} items={[{ key: 'details', label: '滞销明细' }, { key: 'promotion', label: '促销提醒' }]} />
    {tab === 'details' ? <DashboardPage page="slow-moving" /> : <Suspense fallback={<PromotionLoading />}><PromotionBoard /></Suspense>}
  </div>;
}
