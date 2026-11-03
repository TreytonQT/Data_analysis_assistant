import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ConfirmFilterSelect from './ConfirmFilterSelect';

afterEach(cleanup);

const developerOptions = [
  { value: 'lin-26', label: '运营二十七部-林飞扬-26' },
  { value: 'lin-25', label: '运营二十七部-林飞扬-25' },
  { value: 'chen', label: '运营二十七部-陈千潼' },
];

describe('ConfirmFilterSelect', () => {
  it('searches and selects all matching developers without committing before confirm', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect mode="multiple" ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={['lin-25']} options={developerOptions} onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: '开发员: 已选 1 人' }));
    expect(screen.getByRole('checkbox', { name: '全选当前搜索结果' })).toBePartiallyChecked();
    await user.type(screen.getByRole('textbox', { name: '搜索开发员' }), '林飞扬-26');
    const selectAll = screen.getByRole('checkbox', { name: '全选当前搜索结果' });
    await user.click(selectAll);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox', { name: '运营二十七部-林飞扬-26' })).toBeChecked();
    await user.clear(screen.getByRole('textbox', { name: '搜索开发员' }));
    expect(screen.getByRole('checkbox', { name: '运营二十七部-林飞扬-25' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '运营二十七部-陈千潼' })).not.toBeChecked();

    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledWith(['lin-25', 'lin-26']);
  });

  it('discards edits on cancel, Escape, and outside click', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect mode="multiple" ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={[]} options={developerOptions} onConfirm={onConfirm} />);
    const trigger = screen.getByRole('button', { name: '开发员: 全部开发员' });

    await user.click(trigger);
    await user.click(screen.getByRole('checkbox', { name: '运营二十七部-陈千潼' }));
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(trigger);
    const search = screen.getByRole('textbox', { name: '搜索开发员' });
    await user.click(screen.getByRole('checkbox', { name: '运营二十七部-陈千潼' }));
    fireEvent.keyDown(search, { key: 'Escape', code: 'Escape' });
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(trigger);
    await user.click(screen.getByRole('checkbox', { name: '运营二十七部-陈千潼' }));
    await user.click(document.body);
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('immediately applies only the chosen search result and discards other selections and drafts', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={['lin-25']} options={developerOptions} onConfirm={onConfirm} />);
    const trigger = screen.getByRole('button', { name: '开发员: 已选 1 人' });

    await user.click(trigger);
    await user.click(screen.getByRole('checkbox', { name: '运营二十七部-陈千潼' }));
    await user.type(screen.getByRole('textbox', { name: '搜索开发员' }), '林飞扬-26');
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '仅筛选此项：运营二十七部-林飞扬-26' }));

    expect(onConfirm).toHaveBeenCalledExactlyOnceWith(['lin-26']);
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
  });

  it('closes without resubmitting when the only chosen option is already applied', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={['chen']} options={developerOptions} onConfirm={onConfirm} />);
    const trigger = screen.getByRole('button', { name: '开发员: 已选 1 人' });

    await user.click(trigger);
    await user.click(screen.getByRole('checkbox', { name: '运营二十七部-林飞扬-25' }));
    await user.click(screen.getByRole('button', { name: '仅筛选此项：运营二十七部-陈千潼' }));
    expect(onConfirm).not.toHaveBeenCalled();
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
  });

  it('supports keyboard quick selection for numeric single filters and preserves normalized defaults', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const options = [{ value: 30, label: '≥30' }, { value: 50, label: '≥50' }];
    const { rerender } = render(<ConfirmFilterSelect mode="single" ariaLabel="补货数量" placeholder="补货数量门槛" value={30} options={options} onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: '补货数量: ≥30' }));
    screen.getByRole('button', { name: '仅筛选此项：≥50' }).focus();
    await user.keyboard('{Enter}');
    expect(onConfirm).toHaveBeenCalledExactlyOnceWith(50);
    await waitFor(() => expect(screen.getByRole('button', { name: '补货数量: ≥30' })).toHaveAttribute('aria-expanded', 'false'));

    onConfirm.mockClear();
    rerender(<ConfirmFilterSelect mode="single" ariaLabel="补货数量" placeholder="补货数量门槛" options={options} normalizeValue={value => value ?? 30} onConfirm={onConfirm} />);
    const trigger = screen.getByRole('button', { name: '补货数量: 补货数量门槛' });
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: '仅筛选此项：≥30' }));
    expect(onConfirm).not.toHaveBeenCalled();
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
  });

  it('confirms a numeric single selection and skips a semantic no-op', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const { rerender } = render(<ConfirmFilterSelect mode="single" ariaLabel="补货数量" placeholder="补货数量门槛" value={30} options={[{ value: 30, label: '≥30' }, { value: 50, label: '≥50' }]} onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: '补货数量: ≥30' }));
    await user.click(screen.getByRole('radio', { name: '≥50' }));
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledWith(50);

    onConfirm.mockClear();
    rerender(<ConfirmFilterSelect mode="multiple" ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={[]} options={developerOptions} onConfirm={onConfirm} />);
    await user.click(screen.getByRole('button', { name: '开发员: 全部开发员' }));
    await user.click(screen.getByRole('checkbox', { name: '全选当前搜索结果' }));
    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('clears a selection only after confirmation', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect mode="multiple" ariaLabel="开发员" selectionUnit="人" placeholder="全部开发员" value={['chen']} options={developerOptions} onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: '开发员: 已选 1 人' }));
    await user.click(screen.getByRole('button', { name: '清空' }));
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledWith([]);
  });

  it('does not commit when clearing a single filter restores its business default', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmFilterSelect
      mode="single"
      ariaLabel="促销状态"
      placeholder="正在促销"
      value="active"
      options={[{ value: 'active', label: '正在促销' }, { value: 'ended', label: '已结束' }]}
      normalizeValue={value => value || 'active'}
      onConfirm={onConfirm}
    />);

    await user.click(screen.getByRole('button', { name: '促销状态: 正在促销' }));
    await user.click(screen.getByRole('button', { name: '清空' }));
    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
