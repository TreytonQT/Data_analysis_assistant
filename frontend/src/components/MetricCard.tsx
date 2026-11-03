import { Card, Statistic, type StatisticProps } from 'antd';

export type MetricTone = 'default' | 'blue' | 'violet' | 'orange' | 'green' | 'positive' | 'negative';
export interface MetricCardProps extends StatisticProps {
  className?: string;
  tone?: MetricTone;
  variant?: 'card' | 'plain';
}

export default function MetricCard({ className = '', tone = 'default', variant = 'card', ...statistic }: MetricCardProps) {
  if (variant === 'plain') return <div className={`metric-card metric-card-plain metric-card-${tone} ${className}`}>
    <Statistic {...statistic} />
  </div>;
  return <Card className={`metric-card metric-card-${tone} ${className}`}>
    <Statistic {...statistic} />
  </Card>;
}
