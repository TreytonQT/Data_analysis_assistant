import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Input, Popover, Space, Table, Tag, Typography, type TableProps } from 'antd';
import { EditOutlined } from '@ant-design/icons';

import { api, type VariantChild, type VariantGroup, type VariantPage, type VariantFilterStatus } from './api';
import type { PageLifecycleProps } from './pageLifecycle';
import PageHeading from './components/PageHeading';
import { PageLoading, SectionEmpty, SectionError } from './components/PageState';
import ConfirmFilterSelect from './ConfirmFilterSelect';
import FilterActions from './FilterActions';
import SkuImagePreview from './SkuImagePreview';
import { feedbackMessage } from './feedback';
import './VariantManagementPage.css';

const statusLabels = { filled: '已填写', empty: '未填写', pending: '父SKU待确认' };
const defaults = { search: '', status: 'all' as VariantFilterStatus, developers: '', stores: '', page: 1, page_size: 50 };
const childColumns: TableProps<VariantChild>['columns'] = [
  { title: '图片', key: 'image', width: 68, render: (_, child) => <SkuImagePreview image={child.image} alt={child.sku} width={36} height={36} /> },
  { title: 'MSKU', dataIndex: 'sku', width: 190, ellipsis: true },
  { title: '子ASIN', dataIndex: 'asin', width: 140, ellipsis: true },
  { title: '品名', dataIndex: 'product_name', width: 280, ellipsis: true, render: value => value || '—' },
  { title: '开发员', dataIndex: 'developer', width: 180, ellipsis: true, render: value => value || '—' },
  { title: '日均销量（件/天）', dataIndex: 'daily_sales', width: 145, align: 'right', render: value => value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
  { title: '国家 / 父ASIN / 变体属性', key: 'sites', width: 390, render: (_, child) => <div className="variant-sites">{child.sites.map(site => <div key={site.country + site.parent_asin}>
    <span className="variant-country">{site.country}</span><span>{site.parent_asin || '—'}</span><span className="variant-attributes">{site.attributes || '—'}</span>
  </div>)}</div> },
];

export default function VariantManagementPage({ active = true, routeVersion = 0, refreshVersion = 0 }: PageLifecycleProps) {
  const [params, setParams] = useState(defaults);
  const [searchDraft, setSearchDraft] = useState('');
  const [data, setData] = useState<VariantPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState<{ group: VariantGroup; revision: string } | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');
  const requestSequence = useRef(0);
  const saveLock = useRef(false);
  const savedAwaitingRefresh = useRef(false);

  useEffect(() => {
    if (!active && !saveLock.current) setEditing(null);
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const sequence = ++requestSequence.current;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    api.variants(params, controller.signal).then(result => {
      if (controller.signal.aborted || requestSequence.current !== sequence) return;
      setData(result);
      savedAwaitingRefresh.current = false;
    }).catch(reason => {
      if (controller.signal.aborted || requestSequence.current !== sequence) return;
      setError(reason instanceof Error ? reason.message : '变体数据加载失败');
      if (savedAwaitingRefresh.current) {
        feedbackMessage.warning('父SKU已保存，但列表刷新失败，请重试加载');
        savedAwaitingRefresh.current = false;
      }
    }).finally(() => {
      if (!controller.signal.aborted && requestSequence.current === sequence) setLoading(false);
    });
    return () => controller.abort();
  }, [active, routeVersion, refreshVersion, params, reload]);

  const save = async () => {
    if (!editing || saveLock.current) return;
    saveLock.current = true;
    setBusy(true);
    setSaveError('');
    try {
      await api.saveVariantParentSku(editing.group.key, draft, editing.revision);
      savedAwaitingRefresh.current = true;
      setEditing(null);
      feedbackMessage.success('父SKU已保存');
      setReload(value => value + 1);
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : '保存失败，请重试');
    } finally {
      saveLock.current = false;
      setBusy(false);
    }
  };

  const columns: TableProps<VariantGroup>['columns'] = [
    Table.EXPAND_COLUMN,
    { title: '父体图片', key: 'image', width: 86, render: (_, group) => <div title={group.representative_sku ? '代表SKU：' + group.representative_sku : '日均销量缺失，暂无代表图'}><SkuImagePreview image={group.image} alt={group.parent_sku || group.parents[0]?.asin || group.product_name || '未合成变体'} /></div> },
    { title: '店铺', dataIndex: 'store_code', width: 100, ellipsis: true, render: (value, group) => <span title={group.store_inferred ? '店铺根据SKU前缀识别' : '店铺来自运营表'}>{value}</span> },
    { title: '父SKU', dataIndex: 'parent_sku', width: 210, render: (value, group) => <div className="variant-parent-cell"><Popover
      trigger="click" placement="bottomLeft" destroyOnHidden fresh open={active && editing?.group.key === group.key}
      onOpenChange={open => {
        if (busy) return;
        if (open) {
          setEditing({ group, revision: data!.revision });
          setDraft(group.parent_sku);
          setSaveError('');
        } else setEditing(null);
      }}
      content={<div className="variant-editor" role={editing?.group.key === group.key ? 'dialog' : undefined} aria-label="父SKU编辑" onClick={event => event.stopPropagation()} onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.preventDefault(); setEditing(null); } }}>
        {editing?.group.key === group.key && <>
        {editing?.group.status === 'pending' && <Alert type="warning" showIcon message={editing.group.legacy_assignment ? '历史父SKU（店铺待确认）' : '关系已变化，请确认父SKU'} description={<Space wrap>{editing.group.candidate_skus.map(sku => <Button size="small" key={sku} disabled={busy} onClick={() => setDraft(sku)}>{sku}</Button>)}</Space>} />}
        {editing.group.other_parent_skus.length > 0 && <div className="variant-other-parent-skus">
          <Typography.Text type="secondary">其它店铺已记录，点击填入后可修改</Typography.Text>
          {editing.group.other_parent_skus.map(reference => <Button size="small" key={JSON.stringify([reference.store_code, reference.parent_sku])} disabled={busy}
            aria-label={'引用' + reference.store_code + '父SKU：' + reference.parent_sku}
            onClick={() => setDraft(reference.parent_sku)}>{reference.store_code}：{reference.parent_sku}</Button>)}
        </div>}
        <Input.TextArea aria-label="父SKU" autoFocus value={draft} disabled={busy} rows={2} onChange={event => setDraft(event.target.value)} placeholder="请输入父SKU" />
        {saveError && <SectionError title="父SKU未保存" error={saveError} />}
        <div className="variant-editor-actions"><Button size="small" disabled={busy} onClick={() => setEditing(null)}>取消</Button><Button size="small" loading={busy} onClick={() => void save()}>{!draft.trim() && (editing.group.parent_sku || editing.group.status === 'pending') ? '确认清空' : '确定'}</Button></div>
        </>}
      </div>}
    ><Button type="text" size="small" className="variant-parent-sku-trigger" aria-label={group.status === 'pending' ? '确认父SKU' : '编辑父SKU'} aria-expanded={active && editing?.group.key === group.key} disabled={loading || Boolean(error)}>
        <span className="variant-parent-sku-value" title={value || '待填写'}>{value || '待填写'}</span><EditOutlined />
      </Button></Popover>
      {group.other_parent_skus.map(reference => <Typography.Text type="secondary" className="variant-parent-reference"
        key={JSON.stringify([reference.store_code, reference.parent_sku])}
        title={reference.store_code + '已记录：' + reference.parent_sku + '（匹配' + reference.matched_child_asins.length + '/' + group.child_asin_count + '个子ASIN）'}>
        {reference.store_code}已记录：{reference.parent_sku}（匹配{reference.matched_child_asins.length}/{group.child_asin_count}）
      </Typography.Text>)}
    </div> },
    { title: '通用品名', dataIndex: 'product_name', width: 260, ellipsis: true, render: value => value || <Typography.Text type="secondary">品名待归纳</Typography.Text> },
    { title: '父ASIN及国家', key: 'parents', width: 300, render: (_, group) => group.relation_kind === 'unassembled' ? <Tag>未合成变体</Tag> : <div className="variant-parents">{group.parents.map(parent => <div key={parent.asin}><span>{parent.asin}</span><Typography.Text type="secondary">{parent.countries.join(' / ')}</Typography.Text></div>)}</div> },
    { title: '子ASIN数', key: 'count', width: 100, align: 'right', render: (_, group) => group.child_asin_count },
    { title: '填写状态', dataIndex: 'status', width: 110, render: (status: VariantGroup['status']) => <Tag color={status === 'pending' ? 'warning' : undefined}>{statusLabels[status]}</Tag> },
  ];

  return <div className="variant-page">
    <PageHeading title="变体管理" description="显示两个及以上子ASIN的变体组；未合成变体按连续SKU及品名相似度超过80%识别。" actions={<Button disabled={loading} onClick={() => setReload(value => value + 1)}>刷新</Button>} />
    {error && <SectionError title="变体数据加载失败" error={error} onRetry={() => setReload(value => value + 1)} />}
    {data?.warning && <Alert type="warning" showIcon message={data.warning} />}
    <Card>
      <div className="variant-toolbar">
        <Space wrap>
          <Input.Search aria-label="搜索变体" placeholder="搜索品名、父SKU、父ASIN、子ASIN或MSKU" value={searchDraft} allowClear onChange={event => setSearchDraft(event.target.value)} onSearch={value => setParams(current => current.search === value.trim() ? current : { ...current, search: value.trim(), page: 1 })} className="variant-search" />
          <ConfirmFilterSelect mode="single" ariaLabel="变体状态" placeholder="全部状态" value={params.status} options={[{ value: 'all', label: '全部状态' }, { value: 'filled', label: statusLabels.filled }, { value: 'empty', label: statusLabels.empty }, { value: 'unassembled', label: '待合成' }]} onConfirm={value => setParams(current => ({ ...current, status: (value || 'all') as VariantFilterStatus, page: 1 }))} />
          <ConfirmFilterSelect ariaLabel="店铺" placeholder="全部店铺" selectionUnit="店" value={params.stores ? params.stores.split(',') : []} options={(data?.stores || []).map(value => ({ value, label: value }))} onConfirm={value => setParams(current => ({ ...current, stores: Array.isArray(value) ? value.map(String).join(',') : '', page: 1 }))} />
          <ConfirmFilterSelect ariaLabel="开发员" placeholder="全部开发员" selectionUnit="人" value={params.developers ? params.developers.split(',') : []} options={(data?.developers || []).map(value => ({ value, label: value }))} onConfirm={value => setParams(current => ({ ...current, developers: Array.isArray(value) ? value.map(String).join(',') : '', page: 1 }))} />
          <FilterActions onReset={() => { setSearchDraft(''); setParams(defaults); }} />
        </Space>
        <Typography.Text type="secondary">快照：{data?.date || '—'} · 共 {data?.total ?? 0} 组</Typography.Text>
      </div>
      {!data && loading ? <PageLoading label="正在加载变体…" compact /> : !data && error ? null : <Table<VariantGroup>
        size="small" rowKey="key" columns={columns} dataSource={data?.rows || []} loading={loading} scroll={{ x: 1220 }}
        expandable={{ childrenColumnName: 'variantTreeRows', expandedRowRender: group => <Table<VariantChild> size="small" rowKey={child => JSON.stringify([child.sku, child.asin])} columns={childColumns} dataSource={group.children} pagination={false} scroll={{ x: 1393 }} />, rowExpandable: group => group.children.length > 0 }}
        pagination={{ current: data?.page || params.page, pageSize: params.page_size, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], onChange: (page, pageSize) => setParams(current => ({ ...current, page: current.page_size === pageSize ? page : 1, page_size: pageSize })) }}
        locale={{ emptyText: <SectionEmpty description="暂无符合条件的变体组" /> }}
      />}
    </Card>
  </div>;
}
