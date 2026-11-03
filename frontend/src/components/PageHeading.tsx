import type { ReactNode } from 'react';
import { Typography } from 'antd';

export interface PageHeadingProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  density?: 'default' | 'compact';
}

export default function PageHeading({ title, description, actions, className = '', density = 'default' }: PageHeadingProps) {
  return <div className={`page-heading page-heading-${density} ${className}`}>
    <div className="page-heading-copy">
      <Typography.Title level={1}>{title}</Typography.Title>
      {description && <Typography.Text type="secondary">{description}</Typography.Text>}
    </div>
    {actions && <div className="page-heading-actions">{actions}</div>}
  </div>;
}
