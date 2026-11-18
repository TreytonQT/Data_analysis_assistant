import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import VariantManagementPage from './VariantManagementPage';
import type { VariantPage } from './api';

const mocks = vi.hoisted(() => ({ variants: vi.fn(), saveVariantParentSku: vi.fn(), success: vi.fn(), warning: vi.fn() }));
vi.mock('./api', () => ({ api: mocks }));
vi.mock('./feedback', () => ({ feedbackMessage: { success: mocks.success, warning: mocks.warning } }));

function view(): VariantPage {
  return { developers: ['甲', '乙'], stores: ['ZXU', 'YAP'], date: '2026-11-06', revision: 'revision-1', warning: null, total: 1, page: 1, page_size: 50, rows: [{
    key: 'group-1', store_code: 'ZXU', store_inferred: false, other_parent_skus: [], legacy_assignment: false, parent_sku: 'PARENT', product_name: '1条包包链（金）(2.5)', relation_kind: 'assembled', child_asin_count: 2, status: 'filled', candidate_skus: [], image: null, representative_sku: 'SKU-1',
    parents: [{ asin: 'PARENT-ASIN', countries: ['DE', 'FR'] }],
    children: [
      { sku: 'SKU-1', asin: 'CHILD-1', product_name: '1条包包链（金）(2.5)', developer: '甲', daily_sales: 0, image: null, sites: [{ country: 'DE', parent_asin: 'PARENT-ASIN', attributes: '[color:Schwarz]' }] },
      { sku: 'SKU-2', asin: 'CHILD-2', product_name: '1条包包链（银）(2.5)', developer: '', daily_sales: null, image: null, sites: [{ country: 'FR', parent_asin: 'PARENT-ASIN', attributes: '[color:Noir]' }] },
    ],
  }] };
}

describe('VariantManagementPage', () => {
  afterEach(() => {
    cleanup();
    mocks.variants.mockReset();
    mocks.saveVariantParentSku.mockReset();
    vi.clearAllMocks();
  });

  it('starts collapsed and expands complete child details with zero and missing sales', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    await screen.findByText('PARENT');
    expect(screen.queryByText('SKU-1')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Expand row' }));
    expect(await screen.findByText('SKU-1')).toBeTruthy();
    expect(screen.getByText('SKU-2')).toBeTruthy();
    expect(screen.getByText('[color:Noir]')).toBeTruthy();
    expect(screen.getAllByText('1条包包链（金）(2.5)')).toHaveLength(2);
    expect(screen.getByText('0')).toBeTruthy();
  });

  it('does not fetch for a search draft, and status confirmation preserves the applied search', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    await screen.findByText('PARENT');
    const search = screen.getByLabelText('搜索变体');
    fireEvent.change(search, { target: { value: 'CHILD-1' } });
    expect(mocks.variants).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(mocks.variants).toHaveBeenCalledTimes(2));
    fireEvent.change(search, { target: { value: 'UNAPPLIED' } });
    fireEvent.click(screen.getByRole('button', { name: '变体状态: 全部状态' }));
    fireEvent.click(screen.getByRole('radio', { name: '未填写' }));
    fireEvent.click(screen.getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'CHILD-1', status: 'empty', page: 1 }), expect.any(AbortSignal)));
  });

  it('filters unassembled groups while preserving applied search and developers, then resets', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    await screen.findByText('PARENT');
    fireEvent.click(screen.getByRole('button', { name: '开发员: 全部开发员' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '甲' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: '开发员筛选选项' })).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ developers: '甲' }), expect.any(AbortSignal)));
    const search = screen.getByLabelText('搜索变体');
    fireEvent.change(search, { target: { value: 'APPLIED' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'APPLIED' }), expect.any(AbortSignal)));
    fireEvent.change(search, { target: { value: 'DRAFT' } });
    const calls = mocks.variants.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '变体状态: 全部状态' }));
    expect(screen.getAllByRole('radio')).toHaveLength(4);
    expect(screen.queryByRole('radio', { name: '待确认' })).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: '待合成' }));
    expect(mocks.variants).toHaveBeenCalledTimes(calls);
    fireEvent.click(within(screen.getByRole('dialog', { name: '变体状态筛选选项' })).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({
      status: 'unassembled', search: 'APPLIED', developers: '甲', page: 1,
    }), expect.any(AbortSignal)));
    expect(search).toHaveValue('DRAFT');
    fireEvent.click(screen.getByRole('button', { name: '重置筛选' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({
      status: 'all', search: '', developers: '', page: 1,
    }), expect.any(AbortSignal)));
    expect(search).toHaveValue('');
  });

  it('keeps the unassembled filter after saving a parent SKU', async () => {
    const source = view();
    source.rows[0] = { ...source.rows[0], relation_kind: 'unassembled', parents: [], parent_sku: '', status: 'empty' };
    mocks.variants.mockResolvedValue(source);
    mocks.saveVariantParentSku.mockImplementation(async () => {
      source.rows[0] = { ...source.rows[0], parent_sku: 'NEW-PARENT', status: 'filled' };
      return { saved: true, parent_sku: 'NEW-PARENT' };
    });
    render(<VariantManagementPage />);
    await screen.findByText('未合成变体');
    fireEvent.click(screen.getByRole('button', { name: '变体状态: 全部状态' }));
    fireEvent.click(screen.getByRole('radio', { name: '待合成' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: '变体状态筛选选项' })).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'unassembled' }), expect.any(AbortSignal)));
    fireEvent.click(await screen.findByRole('button', { name: '编辑父SKU' }));
    const editor = within(await screen.findByRole('dialog', { name: '父SKU编辑' }));
    fireEvent.change(editor.getByLabelText('父SKU'), { target: { value: 'NEW-PARENT' } });
    fireEvent.click(editor.getByRole('button', { name: /确\s*定/ }));
    expect(await screen.findByText('NEW-PARENT')).toBeTruthy();
    expect(screen.getByText('未合成变体')).toBeTruthy();
    expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'unassembled' }), expect.any(AbortSignal));
  });

  it('confirms store selection and resets without submitting the text draft', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    await screen.findByText('PARENT');
    fireEvent.change(screen.getByLabelText('搜索变体'), { target: { value: 'UNAPPLIED' } });
    fireEvent.click(screen.getByRole('button', { name: '店铺: 全部店铺' }));
    const filter = within(screen.getByRole('dialog', { name: '店铺筛选选项' }));
    fireEvent.click(filter.getByRole('checkbox', { name: 'ZXU' }));
    expect(mocks.variants).toHaveBeenCalledTimes(1);
    fireEvent.click(filter.getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({
      stores: 'ZXU', search: '', page: 1,
    }), expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('button', { name: '重置筛选' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ stores: '' }), expect.any(AbortSignal)));
  });

  it('shows other-store parent SKUs and only saves the user-confirmed custom value', async () => {
    const source = view();
    source.rows[0].other_parent_skus = [{ store_code: 'YAP', parent_sku: 'OTHER-PARENT', matched_child_asins: ['CHILD-1'] }];
    mocks.variants.mockResolvedValue(source);
    mocks.saveVariantParentSku.mockResolvedValue({ saved: true, parent_sku: 'CUSTOM-PARENT' });
    render(<VariantManagementPage />);
    expect(await screen.findByText('YAP已记录：OTHER-PARENT（匹配1/2）')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '编辑父SKU' }));
    const editor = within(await screen.findByRole('dialog', { name: '父SKU编辑' }));
    fireEvent.click(editor.getByRole('button', { name: '引用YAP父SKU：OTHER-PARENT' }));
    expect(editor.getByLabelText('父SKU')).toHaveValue('OTHER-PARENT');
    expect(mocks.saveVariantParentSku).not.toHaveBeenCalled();
    fireEvent.change(editor.getByLabelText('父SKU'), { target: { value: 'CUSTOM-PARENT' } });
    fireEvent.click(editor.getByRole('button', { name: /确\s*定/ }));
    await waitFor(() => expect(mocks.saveVariantParentSku).toHaveBeenCalledWith('group-1', 'CUSTOM-PARENT', 'revision-1'));
    expect(source.rows[0].other_parent_skus[0].parent_sku).toBe('OTHER-PARENT');
  });

  it('identifies historical assignments that require store confirmation', async () => {
    const source = view();
    source.rows[0] = { ...source.rows[0], status: 'pending', parent_sku: '', candidate_skus: ['LEGACY'], legacy_assignment: true };
    mocks.variants.mockResolvedValue(source);
    render(<VariantManagementPage />);
    fireEvent.click(await screen.findByRole('button', { name: '确认父SKU' }));
    const editor = within(await screen.findByRole('dialog', { name: '父SKU编辑' }));
    expect(editor.getByText('历史父SKU（店铺待确认）')).toBeTruthy();
    fireEvent.click(editor.getByRole('button', { name: 'LEGACY' }));
    expect(editor.getByLabelText('父SKU')).toHaveValue('LEGACY');
    expect(mocks.saveVariantParentSku).not.toHaveBeenCalled();
  });

  it('locks a slow save, keeps a failed draft and uses the captured relation revision', async () => {
    mocks.variants.mockResolvedValue(view());
    let rejectSave!: (error: Error) => void;
    mocks.saveVariantParentSku.mockImplementationOnce(() => new Promise((_, reject) => { rejectSave = reject; }));
    render(<VariantManagementPage />);
    fireEvent.click(await screen.findByRole('button', { name: '编辑父SKU' }));
    const modal = within(await screen.findByRole('dialog'));
    fireEvent.change(modal.getByLabelText('父SKU'), { target: { value: 'DRAFT' } });
    const submit = modal.getByRole('button', { name: /确\s*定/ });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(mocks.saveVariantParentSku).toHaveBeenCalledTimes(1);
    expect(modal.getByLabelText('父SKU')).toBeDisabled();
    expect(modal.getByRole('button', { name: /取\s*消/ })).toBeDisabled();
    await act(async () => rejectSave(new Error('变体关系已变化，请刷新')));
    expect(await modal.findByText('变体关系已变化，请刷新')).toBeTruthy();
    expect(modal.getByLabelText('父SKU')).toHaveValue('DRAFT');
    expect(mocks.saveVariantParentSku).toHaveBeenCalledWith('group-1', 'DRAFT', 'revision-1');
  });

  it('explicitly clears a pending assignment and reports refresh failure as a saved result', async () => {
    const pending = view();
    pending.rows[0] = { ...pending.rows[0], parent_sku: '', status: 'pending', candidate_skus: ['OLD-A', 'OLD-B'] };
    mocks.variants.mockResolvedValueOnce(pending).mockRejectedValue(new Error('刷新网络失败'));
    mocks.saveVariantParentSku.mockResolvedValue({ saved: true, parent_sku: '' });
    render(<VariantManagementPage />);
    fireEvent.click(await screen.findByRole('button', { name: '确认父SKU' }));
    expect(screen.getByText('父SKU待确认')).toBeTruthy();
    const modal = within(await screen.findByRole('dialog'));
    expect(modal.getByRole('button', { name: 'OLD-A' })).toBeTruthy();
    fireEvent.click(modal.getByRole('button', { name: '确认清空' }));
    await waitFor(() => expect(mocks.warning).toHaveBeenCalledWith('父SKU已保存，但列表刷新失败，请重试加载'));
    expect(mocks.saveVariantParentSku).toHaveBeenCalledWith('group-1', '', 'revision-1');
    expect(mocks.success).toHaveBeenCalledWith('父SKU已保存');
  });

  it('loads only when active and ignores responses from a previous activation', async () => {
    let completeOld!: (value: VariantPage) => void;
    mocks.variants.mockImplementationOnce(() => new Promise(resolve => { completeOld = resolve; })).mockResolvedValue(view());
    const rendered = render(<VariantManagementPage active={false} />);
    expect(mocks.variants).not.toHaveBeenCalled();
    rendered.rerender(<VariantManagementPage active />);
    rendered.rerender(<VariantManagementPage active={false} />);
    rendered.rerender(<VariantManagementPage active refreshVersion={1} />);
    await screen.findByText('PARENT');
    const old = view();
    old.rows[0].parent_sku = 'STALE';
    await act(async () => completeOld(old));
    expect(screen.queryByText('STALE')).toBeNull();
    expect(screen.getByText('PARENT')).toBeTruthy();
  });

  it('confirms developer selection without submitting the text draft', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    await screen.findByText('PARENT');
    fireEvent.change(screen.getByLabelText('搜索变体'), { target: { value: 'UNAPPLIED' } });
    fireEvent.click(screen.getByRole('button', { name: '开发员: 全部开发员' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '甲' }));
    expect(mocks.variants).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '确定' }));
    await waitFor(() => expect(mocks.variants).toHaveBeenLastCalledWith(expect.objectContaining({ developers: '甲', search: '', page: 1 }), expect.any(AbortSignal)));
  });

  it('cancels the inline draft without saving and reopens the saved value', async () => {
    mocks.variants.mockResolvedValue(view());
    render(<VariantManagementPage />);
    fireEvent.click(await screen.findByRole('button', { name: '编辑父SKU' }));
    const editor = within(await screen.findByRole('dialog', { name: '父SKU编辑' }));
    fireEvent.change(editor.getByLabelText('父SKU'), { target: { value: 'DISCARDED' } });
    fireEvent.click(editor.getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '父SKU编辑' })).toBeNull());
    expect(mocks.saveVariantParentSku).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '编辑父SKU' }));
    expect(await screen.findByLabelText('父SKU')).toHaveValue('PARENT');
  });

  it('shows unassembled families without inventing a parent ASIN', async () => {
    const source = view();
    source.rows[0] = { ...source.rows[0], relation_kind: 'unassembled', product_name: '1条包包链', parents: [], parent_sku: '', status: 'empty' };
    mocks.variants.mockResolvedValue(source);
    render(<VariantManagementPage />);
    expect(await screen.findByText('未合成变体')).toBeTruthy();
    expect(screen.getByText('1条包包链')).toBeTruthy();
    expect(screen.getByText('待填写')).toBeTruthy();
    expect(screen.queryByText('PARENT-ASIN')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '编辑父SKU' }));
    fireEvent.keyDown(await screen.findByLabelText('父SKU'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '父SKU编辑' })).toBeNull());
  });
});
