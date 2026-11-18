import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Stage } from './App';
import { processFiles, saveResult, WorkbookError, type Preview } from './api';

vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  processFiles: vi.fn(), saveResult: vi.fn(),
}));
vi.mock('../feedback', () => ({
  configureFeedback: vi.fn(), feedbackMessage: { error: vi.fn() },
  isAbortError: (error: unknown) => error instanceof DOMException && error.name === 'AbortError',
  runOperation: (operation: () => Promise<unknown>) => operation(),
}));

const mapping = new File(['mapping'], 'mapping.xlsx');
const first = new File(['oa'], 'oa.xlsx');
const second = new File(['prices'], 'prices.xlsx');
const onBusy = vi.fn();
const preview: Preview = {
  result_id: 'result-1', filename: 'result.xlsx',
  columns: ['SKU', 'DE_PRICE'], rows: [{ SKU: 'new-001', DE_PRICE: 0 }], warnings: [],
  summary: { matched_rows: 1, output_rows: 1, source_rows: 2, fallback_prices: 0 },
};
function uploadSources() {
  fireEvent.change(screen.getByLabelText('上传原店铺OA信息'), { target: { files: [first] } });
  fireEvent.change(screen.getByLabelText('上传原店铺领星售价表'), { target: { files: [second] } });
}
function stage(file: File | null = mapping) {
  return <Stage kind="oa" mapping={file} outputDir="D:/results" onBusy={onBusy} />;
}

describe('follow-sell stage', () => {
  afterEach(cleanup);
  beforeEach(() => { vi.mocked(processFiles).mockReset(); vi.mocked(saveResult).mockReset(); vi.mocked(processFiles).mockResolvedValue(preview); });

  it('validates selected files, preserves zero and saves once on repeated clicks', async () => {
    render(stage()); uploadSources();
    fireEvent.click(screen.getByRole('button', { name: '校验并预览OA结果' }));
    await screen.findByText('new-001');
    expect(processFiles).toHaveBeenCalledWith('oa', [mapping, first, second], expect.any(AbortSignal));
    expect(screen.getByRole('cell', { name: '0' })).toBeVisible();
    let resolveSave!: (value: { path: string }) => void;
    vi.mocked(saveResult).mockReturnValue(new Promise(resolve => { resolveSave = resolve; }));
    const save = screen.getByRole('button', { name: '保存结果1' });
    fireEvent.click(save); fireEvent.click(save);
    expect(saveResult).toHaveBeenCalledTimes(1);
    await act(async () => resolveSave({ path: 'D:/results/output.xlsx' }));
    expect(await screen.findByText('D:/results/output.xlsx')).toBeVisible();
    expect(saveResult).toHaveBeenCalledWith('result-1', 'D:/results');
  });

  it('shows row-specific errors and prevents export', async () => {
    vi.mocked(processFiles).mockRejectedValue(new WorkbookError('整批暂停', [{ file: 'mapping.xlsx', row: 3, sku: 'new-1', message: '新SKU重复' }]));
    render(stage()); uploadSources();
    fireEvent.click(screen.getByRole('button', { name: '校验并预览OA结果' }));
    expect(await screen.findByText('新SKU重复')).toBeVisible();
    expect(screen.getByText('mapping.xlsx · 第3行')).toBeVisible();
    expect(screen.queryByRole('button', { name: '保存结果1' })).toBeNull();
  });

  it('invalidates preview after a file is replaced', async () => {
    render(stage()); uploadSources();
    fireEvent.click(screen.getByRole('button', { name: '校验并预览OA结果' }));
    await screen.findByText('new-001');
    fireEvent.change(screen.getByLabelText('上传原店铺领星售价表'), { target: { files: [new File(['replacement'], 'new-prices.xlsx')] } });
    expect(screen.queryByText('new-001')).toBeNull();
    expect(screen.queryByRole('button', { name: '保存结果1' })).toBeNull();
    expect(screen.getByText('new-prices.xlsx')).toBeVisible();
  });

  it('aborts and ignores an old response after mapping changes', async () => {
    let resolve!: (value: Preview) => void;
    vi.mocked(processFiles).mockReturnValue(new Promise(done => { resolve = done; }));
    const view = render(stage()); uploadSources();
    fireEvent.click(screen.getByRole('button', { name: '校验并预览OA结果' }));
    const signal = vi.mocked(processFiles).mock.calls[0][2];
    view.rerender(stage(new File(['new mapping'], 'new-mapping.xlsx')));
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(preview));
    await waitFor(() => expect(screen.queryByText('new-001')).toBeNull());
    expect(screen.queryByRole('button', { name: '保存结果1' })).toBeNull();
  });

  it('retains a valid preview when saving fails so the user can retry', async () => {
    vi.mocked(saveResult).mockRejectedValueOnce(new Error('目录不可写')).mockResolvedValueOnce({ path: 'D:/results/retry.xlsx' });
    render(stage()); uploadSources();
    fireEvent.click(screen.getByRole('button', { name: '校验并预览OA结果' }));
    await screen.findByText('new-001');
    fireEvent.click(screen.getByRole('button', { name: '保存结果1' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /保存结果1/ })).not.toBeDisabled();
      expect(screen.getByRole('button', { name: /保存结果1/ })).not.toHaveClass('ant-btn-loading');
    });
    fireEvent.click(screen.getByRole('button', { name: /保存结果1/ }));
    expect(saveResult).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('D:/results/retry.xlsx')).toBeVisible();
  });
});
