import { useState, type ReactNode } from 'react';
import { Button, Card, Tabs } from 'antd';

import type { DashboardMetric, DashboardSection } from './api';
import { SectionEmpty } from './components/PageState';

interface OverviewBoardProps {
  metrics: DashboardMetric[];
  sections: DashboardSection[];
  sectionCards: ReactNode[];
  renderMetric: (metric: DashboardMetric) => ReactNode;
  renderChart: (section: DashboardSection) => ReactNode;
}

const summaryNames = ['销售额', '销量', '毛利润', '毛利率', '广告费', '广告费占比'];
const detailOrder = ['stores', 'developer-stores', 'commission', 'alerts', 'developers', 'trend'];

export default function OverviewBoard({ metrics, sections, sectionCards, renderMetric, renderChart }: OverviewBoardProps) {
  const [selectedDetail, setSelectedDetail] = useState('stores');
  const byName = new Map(metrics.map(metric => [metric.name, metric]));
  const trend = sections.find(section => section.key === 'trend');
  const developers = sections.find(section => section.key === 'developers');
  const hasSales = byName.has('销售额') || byName.has('销量') || Boolean(trend);
  const hasFinance = summaryNames.slice(2).some(name => byName.has(name));
  const metricGroup = (names: string[]) => names.flatMap(name => {
    const metric = byName.get(name);
    return metric ? [renderMetric(metric)] : [];
  });
  const extraMetrics = metrics.filter(metric => !summaryNames.includes(metric.name));
  const details = sections.map((section, index) => ({
    key: section.key, label: section.title, children: sectionCards[index],
  })).sort((left, right) => {
    const position = (key: string) => detailOrder.includes(key) ? detailOrder.indexOf(key) : detailOrder.length;
    return position(left.key) - position(right.key);
  });
  const activeDetail = details.some(item => item.key === selectedDetail) ? selectedDetail : details[0]?.key;

  if (!metrics.length && !sections.length) return null;

  return <div className="overview-board">
    {(hasSales || hasFinance) && <div className={`overview-summary-grid${hasSales ? '' : ' overview-summary-grid-no-sales'}`}>
      {hasSales && <Card className="overview-sales-card">
        <div className="overview-sales-metrics">{metricGroup(['销售额', '销量'])}</div>
        {trend && <div className="overview-trend">
          <div className="overview-section-heading"><h3>{trend.title}</h3><span>销售额 · 万元</span></div>
          {trend.rows.length ? renderChart(trend) : <SectionEmpty description="暂无月度趋势数据" />}
        </div>}
      </Card>}
      <div className="overview-finance-stack">
        {['毛利润', '毛利率'].some(name => byName.has(name)) && <Card title="利润表现" className="overview-finance-card">
          <div className="overview-paired-metrics">{metricGroup(['毛利润', '毛利率'])}</div>
          {developers && <div className="overview-finance-action"><Button type="text" size="small" onClick={() => setSelectedDetail('developers')}>查看开发员分析 →</Button></div>}
        </Card>}
        {['广告费', '广告费占比'].some(name => byName.has(name)) && <Card title="广告投入" className="overview-finance-card">
          <div className="overview-paired-metrics">{metricGroup(['广告费', '广告费占比'])}</div>
          {sections.some(section => section.key === 'stores') && <div className="overview-finance-action"><Button type="text" size="small" onClick={() => setSelectedDetail('stores')}>查看店铺分析 →</Button></div>}
        </Card>}
      </div>
    </div>}
    {extraMetrics.length > 0 && <div className="overview-extra-metrics">{extraMetrics.map(renderMetric)}</div>}
    <div className={`overview-detail-grid${developers ? '' : ' overview-detail-grid-single'}`}>
      {details.length > 0 && <div className="overview-details">
        <Tabs activeKey={activeDetail} onChange={setSelectedDetail} items={details} destroyOnHidden={false} />
      </div>}
      {developers && <Card className="overview-ranking-card" title={developers.title}
        extra={<Button type="text" size="small" onClick={() => setSelectedDetail('developers')}>查看明细</Button>}>
        {developers.rows.length ? renderChart({ ...developers, rows: developers.rows.slice(0, 5) }) : <SectionEmpty />}
      </Card>}
    </div>
  </div>;
}
