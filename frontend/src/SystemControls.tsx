import { useEffect, useRef, useState } from 'react';
import { Button, Modal, Result, Space, Spin, Typography } from 'antd';
import { PoweroffOutlined, ReloadOutlined } from '@ant-design/icons';

import { api, type SystemStatus } from './api';


type ControlPhase = 'idle' | 'restarting' | 'shutting-down' | 'stopped' | 'failed';
type ConfirmAction = 'restart' | 'shutdown' | null;

export interface SystemControlsProps {
  onRestarted?: () => void;
  pollDelayMs?: number;
  restartTimeoutMs?: number;
  shutdownTimeoutMs?: number;
}

const wait = (milliseconds: number) => new Promise<void>(resolve => window.setTimeout(resolve, milliseconds));

export default function SystemControls({
  onRestarted = () => window.location.reload(),
  pollDelayMs = 500,
  restartTimeoutMs = 60_000,
  shutdownTimeoutMs = 15_000,
}: SystemControlsProps) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [phase, setPhase] = useState<ControlPhase>('idle');
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [failureMessage, setFailureMessage] = useState('');
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void api.systemStatus().then(value => {
      if (mounted.current) setStatus(value);
    }).catch(() => {
      if (mounted.current) setStatus(null);
    });
    return () => { mounted.current = false; };
  }, []);

  const waitForRestart = async (previousInstanceId: string) => {
    const deadline = Date.now() + restartTimeoutMs;
    while (Date.now() < deadline) {
      try {
        const next = await api.systemStatus();
        if (!mounted.current) return;
        setStatus(next);
        if (next.control_available && next.instance_id !== previousInstanceId) {
          onRestarted();
          return;
        }
      } catch {
        // The old process is expected to be briefly unavailable while it restarts.
      }
      await wait(pollDelayMs);
    }
    if (mounted.current) {
      setFailureMessage('重启超过 60 秒仍未恢复，请通过桌面“销售数据看板”快捷方式重新启动。');
      setPhase('failed');
    }
  };

  const waitForShutdown = async () => {
    const deadline = Date.now() + shutdownTimeoutMs;
    while (Date.now() < deadline) {
      try {
        await api.systemStatus();
      } catch {
        if (mounted.current) setPhase('stopped');
        return;
      }
      await wait(pollDelayMs);
    }
    if (mounted.current) {
      setFailureMessage('系统尚未完全退出，请稍后重试，或从桌面快捷方式重新启动服务。');
      setPhase('failed');
    }
  };

  const restart = async () => {
    setPhase('restarting');
    try {
      const response = await api.restartSystem();
      await waitForRestart(response.instance_id);
    } catch (error) {
      if (mounted.current) {
        setFailureMessage(error instanceof Error ? error.message : '重启请求失败');
        setPhase('failed');
      }
    }
  };

  const shutdown = async () => {
    setPhase('shutting-down');
    try {
      await api.shutdownSystem();
      await waitForShutdown();
    } catch (error) {
      if (mounted.current) {
        setFailureMessage(error instanceof Error ? error.message : '退出请求失败');
        setPhase('failed');
      }
    }
  };

  const available = status?.control_available === true;
  const busy = phase === 'restarting' || phase === 'shutting-down';
  const unavailableHint = status?.control_available === false ? '当前启动方式不支持系统控制' : '正在检查系统控制状态';

  const confirm = () => {
    const action = confirmAction;
    setConfirmAction(null);
    if (action === 'restart') void restart();
    if (action === 'shutdown') void shutdown();
  };

  return <>
    <Space className="system-actions" size={8}>
      <Button icon={<ReloadOutlined />} onClick={() => setConfirmAction('restart')} disabled={!available || busy} title={!available ? unavailableHint : undefined}>重启系统</Button>
      <Button danger icon={<PoweroffOutlined />} onClick={() => setConfirmAction('shutdown')} disabled={!available || busy} title={!available ? unavailableHint : undefined}>退出系统</Button>
    </Space>
    <Modal
      open={confirmAction !== null}
      title={confirmAction === 'restart' ? '确认重启系统？' : '确认退出系统？'}
      okText={confirmAction === 'restart' ? '重启' : '退出系统'}
      cancelText="取消"
      okButtonProps={confirmAction === 'shutdown' ? { danger: true } : undefined}
      onCancel={() => setConfirmAction(null)}
      onOk={confirm}
    >
      {confirmAction === 'restart'
        ? '当前页面会短暂断开，服务恢复后将自动刷新当前页面。'
        : '退出后看板将无法访问，需要通过桌面“销售数据看板”快捷方式重新启动。'}
    </Modal>
    {phase === 'restarting' || phase === 'shutting-down' ? <div className="system-control-overlay" role="status" aria-live="polite">
      <div className="system-control-card"><Spin size="large" /><Typography.Title level={4}>{phase === 'restarting' ? '系统正在重启…' : '系统正在退出…'}</Typography.Title><Typography.Text type="secondary">{phase === 'restarting' ? '服务恢复后会自动回到当前页面。' : '请稍候，服务停止后会显示启动指引。'}</Typography.Text></div>
    </div> : null}
    {phase === 'stopped' ? <div className="system-control-overlay" role="status" aria-live="polite">
      <div className="system-control-card"><Result status="success" title="系统已退出" subTitle="请双击桌面上的“销售数据看板”快捷方式重新启动。" /></div>
    </div> : null}
    {phase === 'failed' ? <div className="system-control-overlay" role="alert">
      <div className="system-control-card"><Result status="warning" title="系统操作未完成" subTitle={failureMessage} extra={<Button onClick={() => setPhase('idle')}>关闭提示</Button>} /></div>
    </div> : null}
  </>;
}
