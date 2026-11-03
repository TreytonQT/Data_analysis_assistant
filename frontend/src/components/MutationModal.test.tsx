import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MutationModal from './MutationModal';

afterEach(cleanup);

describe('MutationModal', () => {
  it('keeps an in-flight draft open and restores cancel after the request finishes', () => {
    const onCancel = vi.fn();
    const onOk = vi.fn();
    const { rerender } = render(<MutationModal open busy title="保存配置" okText="保存" onOk={onOk} onCancel={onCancel}>当前草稿</MutationModal>);
    const cancel = screen.getByRole('button', { name: /取.*消/ });
    expect(cancel).toBeDisabled();
    expect(screen.queryByRole('button', { name: /close/i })).not.toBeInTheDocument();
    fireEvent.click(cancel);
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByText('当前草稿')).toBeInTheDocument();
    rerender(<MutationModal open busy={false} title="保存配置" okText="保存" onOk={onOk} onCancel={onCancel}>当前草稿</MutationModal>);
    fireEvent.click(screen.getByRole('button', { name: /取.*消/ }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
