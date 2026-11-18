import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ConfigCenter from './ConfigCenter';
import DesignSystemProvider from './DesignSystemProvider';
import { api, type ConfigData } from './api';
import { feedbackMessage } from './feedback';

const config = {
  name: 'replenishment_switches', title: '补货开关', description: '按ASIN维护开关',
  columns: ['ASIN', '是否补货', '关闭原因'], rows: [{ ASIN: 'ASIN-A', 是否补货: '是', 关闭原因: '' }],
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });

const storeConfig = {
  name: 'store_config', title: '店铺配置', description: '维护店铺类型、停提款月份和所属部门。',
  columns: ['店铺名', '店铺类型', '停提款时间', '店铺所属部门'],
  rows: [{ 店铺名: 'TEST', 店铺类型: '本土', 停提款时间: '2026-04', 店铺所属部门: '联合部门' }],
};

function setup(initialConfig: ConfigData = config) {
  window.history.replaceState({}, '', `/?page=config&config_tab=${initialConfig.name}`);
  vi.spyOn(api, 'configs').mockResolvedValue({ configs: [initialConfig] });
  render(<DesignSystemProvider dark={false}><ConfigCenter /></DesignSystemProvider>);
}

describe('configuration editing contract', () => {
  it('keeps the edited draft when reload is cancelled', async () => {
    const user = userEvent.setup();
    setup();
    const asin = await screen.findByDisplayValue('ASIN-A');
    await user.clear(asin);
    await user.type(asin, 'ASIN-B');
    await user.click(screen.getByRole('button', { name: /重新载入/ }));
    expect(await screen.findByText('放弃全部未保存修改并重新载入吗？')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /取.*消/ }));
    expect(screen.getByDisplayValue('ASIN-B')).toBeInTheDocument();
    expect(api.configs).toHaveBeenCalledOnce();
  });

  it('uses the shared upload method and retains returned rows', async () => {
    const user = userEvent.setup();
    const upload = vi.spyOn(api, 'uploadConfig').mockResolvedValue({ rows: [{ ASIN: 'ASIN-IMPORTED', 是否补货: '否', 关闭原因: '暂缓' }] });
    vi.spyOn(feedbackMessage, 'loading').mockImplementation(() => undefined as never);
    vi.spyOn(feedbackMessage, 'success').mockImplementation(() => undefined as never);
    setup();
    await screen.findByDisplayValue('ASIN-A');
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['csv'], 'switches.csv', { type: 'text/csv' });
    await user.upload(input, file);
    await waitFor(() => expect(upload).toHaveBeenCalledWith('replenishment_switches', file));
    expect(await screen.findByDisplayValue('ASIN-IMPORTED')).toBeInTheDocument();
  });

  it('selects a month and one of the two departments, saving canonical fields while locking pending edits', async () => {
    const user = userEvent.setup();
    let finishSave!: (result: Awaited<ReturnType<typeof api.saveConfig>>) => void;
    const save = vi.spyOn(api, 'saveConfig').mockImplementation(() => new Promise(resolve => { finishSave = resolve; }));
    vi.spyOn(feedbackMessage, 'loading').mockImplementation(() => undefined as never);
    vi.spyOn(feedbackMessage, 'success').mockImplementation(() => undefined as never);
    setup(storeConfig);

    const month = await screen.findByRole('textbox', { name: '停提款月份' });
    expect(screen.getByRole('columnheader', { name: '停提款月份' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: '停提款时间' })).not.toBeInTheDocument();
    expect(month).toHaveValue('2026-04');
    expect(month).toHaveAttribute('readonly');
    await user.type(month, '2030-12');
    expect(month).toHaveValue('2026-04');
    await user.click(screen.getByTitle('2026-08'));
    expect(month).toHaveValue('2026-08');

    const department = screen.getByRole('combobox', { name: '店铺所属部门' });
    expect(department).toHaveAttribute('readonly');
    await user.click(department);
    const options = within(screen.getByRole('listbox')).getAllByRole('option');
    expect(options.map(option => option.textContent)).toEqual(['联合部门', '运营二十部']);
    await user.click(screen.getByText('运营二十部', { selector: '.ant-select-item-option-content' }));
    await user.click(screen.getByRole('button', { name: /校验并保存/ }));
    const expected = [{ ...storeConfig.rows[0], 停提款时间: '2026-08', 店铺所属部门: '运营二十部' }];
    expect(save).toHaveBeenCalledExactlyOnceWith('store_config', expected);
    expect(month).toBeDisabled();
    expect(department).toBeDisabled();
    finishSave({ ok: true, rows: expected });
    await waitFor(() => expect(month).toBeEnabled());
    expect(screen.getByRole('button', { name: /校验并保存/ })).toBeDisabled();
  });

  it('clears optional store selections and retains the draft for retry after a failed save', async () => {
    const user = userEvent.setup();
    const expected = [{ ...storeConfig.rows[0], 停提款时间: '', 店铺所属部门: '' }];
    const save = vi.spyOn(api, 'saveConfig').mockRejectedValueOnce(new Error('保存暂时失败')).mockResolvedValueOnce({ ok: true, rows: expected });
    vi.spyOn(feedbackMessage, 'loading').mockImplementation(() => undefined as never);
    vi.spyOn(feedbackMessage, 'error').mockImplementation(() => undefined as never);
    vi.spyOn(feedbackMessage, 'success').mockImplementation(() => undefined as never);
    setup(storeConfig);
    const month = await screen.findByRole('textbox', { name: '停提款月份' });
    await user.click(screen.getByRole('button', { name: 'close-circle' }));
    const department = screen.getByRole('combobox', { name: '店铺所属部门' });
    const departmentField = department.closest('.ant-select') as HTMLElement;
    await user.click(departmentField.querySelector('.ant-select-clear') as HTMLElement);
    await user.click(screen.getByRole('button', { name: /校验并保存/ }));
    expect(await screen.findByText('保存暂时失败')).toBeInTheDocument();
    expect(month).toHaveValue('');
    expect(departmentField).toHaveTextContent('选择所属部门');
    expect(save).toHaveBeenLastCalledWith('store_config', expected);
    await user.click(screen.getByRole('button', { name: /校验并保存/ }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenLastCalledWith('store_config', expected);
  });
});
