import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SystemControls from './SystemControls';

const apiMocks = vi.hoisted(() => ({
  systemStatus: vi.fn(),
  restartSystem: vi.fn(),
  shutdownSystem: vi.fn(),
}));

vi.mock('./api', () => ({ api: apiMocks }));

const oldInstance = { control_available: true, instance_id: 'old', pending_action: null } as const;

function buttonFor(label: string): HTMLButtonElement {
  return screen.getByText(label).closest('button')!;
}

describe('SystemControls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    document.querySelectorAll('.ant-modal-root').forEach(node => node.remove());
  });

  it('disables both controls when the runner is unavailable', async () => {
    apiMocks.systemStatus.mockResolvedValue({ control_available: false, instance_id: 'dev', pending_action: null });

    render(<SystemControls />);

    await screen.findByText('重启系统');
    expect(buttonFor('重启系统')).toBeDisabled();
    expect(buttonFor('退出系统')).toBeDisabled();
  });

  it('restarts after confirmation and reloads only after a new instance is available', async () => {
    const onRestarted = vi.fn();
    apiMocks.systemStatus.mockResolvedValueOnce(oldInstance).mockResolvedValueOnce({ ...oldInstance, instance_id: 'new' });
    apiMocks.restartSystem.mockResolvedValue({ ok: true, action: 'restart', ...oldInstance });
    const user = userEvent.setup();

    render(<SystemControls onRestarted={onRestarted} pollDelayMs={1} restartTimeoutMs={100} />);
    await waitFor(() => expect(buttonFor('重启系统')).toBeEnabled());
    await user.click(buttonFor('重启系统'));
    await waitFor(() => expect(document.querySelector('.ant-modal .ant-btn-primary')).not.toBeNull());
    await user.click(document.querySelector('.ant-modal .ant-btn-primary') as HTMLButtonElement);

    await waitFor(() => expect(apiMocks.restartSystem).toHaveBeenCalledOnce());
    await waitFor(() => expect(onRestarted).toHaveBeenCalledOnce());
  });

  it('shows desktop-start guidance after a confirmed shutdown', async () => {
    apiMocks.systemStatus.mockResolvedValueOnce(oldInstance).mockRejectedValueOnce(new Error('offline'));
    apiMocks.shutdownSystem.mockResolvedValue({ ok: true, action: 'shutdown', ...oldInstance });
    const user = userEvent.setup();

    render(<SystemControls pollDelayMs={1} shutdownTimeoutMs={100} />);
    await waitFor(() => expect(buttonFor('退出系统')).toBeEnabled());
    await user.click(buttonFor('退出系统'));
    await user.click((await screen.findAllByText('退出系统')).at(-1)!.closest('button')!);

    expect(await screen.findByText('系统已退出')).toBeInTheDocument();
    expect(screen.getByText(/桌面上的“销售数据看板”快捷方式/)).toBeInTheDocument();
  });
});
