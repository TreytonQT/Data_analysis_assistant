import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TaskBoard from './TaskBoard';
import { api, type Task } from './api';
import { feedbackMessage } from './feedback';

const saved: Task = {
  id: 'task-1', title: '核对库存', notes: '', status: 'todo', recurrence_type: 'none', recurrence_days: [],
  created_at: '2026-10-29T00:00:00Z', updated_at: '2026-10-29T00:00:00Z', sort_order: 0, is_overdue: false,
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('task form submission', () => {
  it('preserves the original task payload and holds the draft until a slow save finishes', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'tasks').mockResolvedValue([]);
    let finish!: (task: Task) => void;
    const create = vi.spyOn(api, 'createTask').mockImplementation(() => new Promise<Task>(resolve => { finish = resolve; }));
    vi.spyOn(feedbackMessage, 'success').mockImplementation(() => undefined as never);
    render(<TaskBoard active onTasksChanged={vi.fn()} />);
    await waitFor(() => expect(api.tasks).toHaveBeenCalledOnce());
    await user.click(screen.getByRole('button', { name: /新增任务/ }));
    const title = screen.getByLabelText('任务标题');
    await user.type(title, '核对库存');
    await user.click(screen.getByRole('button', { name: /保.*存/ }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(create).toHaveBeenCalledWith(expect.objectContaining({
      title: '核对库存', status: 'todo', recurrence_type: 'none', recurrence_days: [], due_at: null, remind_at: null,
    }));
    expect(title).toHaveValue('核对库存');
    expect(title).toBeDisabled();
    expect(screen.getByRole('button', { name: /取.*消/ })).toBeDisabled();
    await act(async () => finish(saved));
    await waitFor(() => expect(api.tasks).toHaveBeenCalledTimes(2));
  });
});
