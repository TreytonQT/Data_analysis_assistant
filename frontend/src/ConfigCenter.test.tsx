import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ConfigCenter from './ConfigCenter';
import DesignSystemProvider from './DesignSystemProvider';
import { api } from './api';
import { feedbackMessage } from './feedback';

const config = {
  name: 'replenishment_switches', title: '补货开关', description: '按ASIN维护开关',
  columns: ['ASIN', '是否补货', '关闭原因'], rows: [{ ASIN: 'ASIN-A', 是否补货: '是', 关闭原因: '' }],
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });

function setup() {
  window.history.replaceState({}, '', '/?page=config&config_tab=replenishment_switches');
  vi.spyOn(api, 'configs').mockResolvedValue({ configs: [config] });
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
});
