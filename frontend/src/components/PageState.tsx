import { Alert, Button, Empty, Space, Spin, Typography } from 'antd';

export function PageLoading({ label = '正在加载页面…', compact = false }: { label?: string; compact?: boolean }) {
  return <div className={compact ? 'drawer-route-loading' : 'route-loading'} role="status" aria-live="polite">
    <Space direction="vertical" align="center">
      <Spin size="large" />
      <Typography.Text type="secondary">{label}</Typography.Text>
    </Space>
  </div>;
}

export function SectionError({ title, error, onRetry }: { title: string; error: string; onRetry?: () => void }) {
  return <Alert className="section-load-error" type="error" showIcon message={title} description={error}
    action={onRetry && <Button size="small" onClick={onRetry}>重试</Button>} />;
}

export function SectionEmpty({ description = '暂无数据' }: { description?: string }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />;
}
