import { useEffect, useRef, useState } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import { Alert, Button, Card, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { api, type AdjustmentInput, type PricingBatch, type PricingHistoryRow } from './api';
import { feedbackMessage as message } from './feedback';

export function pricingPercent(value?: number) {
  return value == null ? '-' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) + '%';
}
export function combinedDiscount(adjustment: number, promotion: number) {
  return 100 - (100 - adjustment) * (1 - promotion / 100);
}
type Values = { kind: 'adjustment' | 'promotion'; name: string; skus: string; discount: number; start: Dayjs; end?: Dayjs };

export function PricingRegistration({ open, skus, discount, onClose, onSaved }: {
  open: boolean; skus?: string[]; discount?: number; onClose: () => void; onSaved: () => void;
}) {
  const [form] = Form.useForm<Values>();
  const kind = Form.useWatch('kind', form);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const requestId = useRef('');
  const [preview, setPreview] = useState<{ payload: AdjustmentInput; rows: { sku: string; current: number; before: number; after: number; actual_prices?: Record<string, { launch_price: number | null; current_price: number | null; estimated_after_price: number | null }> }[] } | null>(null);
  useEffect(() => {
    if (!open) return;
    requestId.current = crypto.randomUUID();
    setPreview(null); setError('');
    form.resetFields();
    form.setFieldsValue({ kind: 'promotion', name: '', skus: skus?.join('\n') || '', discount: discount || 10, start: dayjs() });
  }, [open, skus, discount, form]);
  const submit = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const v = await form.validateFields();
      const selected = [...new Set(v.skus.split(/\r?\n/).map(s => s.normalize('NFKC').trim()).filter(Boolean))];
      if (v.kind === 'adjustment') {
        const payload: AdjustmentInput = { request_id: requestId.current, batch_name: v.name, skus: selected, discount_percent: v.discount, effective_date: v.start.format('YYYY-MM-DD') };
        if (!preview) {
          const result = await api.previewAdjustment(payload);
          setPreview({ payload, rows: result.rows });
          return;
        }
        await api.createAdjustment(preview.payload);
      } else {
        const payload = { promotion_name: v.name, discount_percent: v.discount, start_date: v.start.format('YYYY-MM-DD'), end_date: v.end!.format('YYYY-MM-DD') };
        if (skus) await api.createPromotions(selected, payload);
        else await api.createManualPromotions(selected, payload);
      }
      message.success('登记成功；本操作未修改平台售价');
      onSaved(); onClose();
    } catch (reason) {
      if (reason instanceof Error) setError(reason.message);
    } finally { lock.current = false; setBusy(false); }
  };
  return <Modal title="登记调价或限时促销" open={open} onCancel={() => { if (!busy) onClose(); }}
    onOk={() => void submit()} okText={kind === 'adjustment' ? preview ? '确认登记调价' : '预览调价影响' : '登记限时促销'}
    confirmLoading={busy} cancelButtonProps={{ disabled: busy }} maskClosable={!busy} closable={!busy}>
    <Alert type="info" showIcon message="仅登记与监控，不修改电商平台售价" description="长期调价累乘；限时优惠作用于调价后的价格。" />
    {error && <Alert type="error" message={error} />}
    <Form form={form} layout="vertical" disabled={busy || !!preview}>
      <Form.Item name="kind" label="记录类型"><Select options={[{ value: 'promotion', label: '限时促销（额外优惠）' }, { value: 'adjustment', label: '长期调价（再次降价会累计）' }]} /></Form.Item>
      <Form.Item name="name" label={kind === 'adjustment' ? '调价批次名称' : '活动名称'} rules={[{ required: true, whitespace: true, max: 100 }]}><Input maxLength={100} /></Form.Item>
      <Form.Item name="skus" label="SKU（一行一个）" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={4} readOnly={!!skus} /></Form.Item>
      <Form.Item name="discount" label={kind === 'adjustment' ? '本次降幅（%）' : '限时额外优惠（%）'} rules={[{ required: true }]}><InputNumber min={1} max={99} precision={0} disabled={busy || !!preview || (!!skus && kind === 'promotion')} /></Form.Item>
      <Form.Item name="start" label={kind === 'adjustment' ? '生效日期' : '开始日期'} rules={[{ required: true }]}><DatePicker /></Form.Item>
      {kind !== 'adjustment' && <Form.Item name="end" label="结束日期（含当天）" dependencies={['start']} rules={[
        { required: true, message: '限时促销必须填写结束日期' },
        ({ getFieldValue }) => ({ validator(_, value?: Dayjs) { return value?.isBefore(getFieldValue('start'), 'day') ? Promise.reject(new Error('结束日期不能早于开始日期')) : Promise.resolve(); } }),
      ]}><DatePicker /></Form.Item>}
    </Form>
    {preview && <>
      <Typography.Paragraph>“登记后累计”按所选生效日期计算；未来调价不影响当前累计。基准为最早已知调价前的价格。</Typography.Paragraph>
      <Table size="small" rowKey="sku" dataSource={preview.rows} pagination={{ pageSize: 8 }} columns={[
        { title: 'SKU', dataIndex: 'sku' },
        { title: '四站价格（开售 / 当前 / 预计）', render: (_, row) => Object.entries(row.actual_prices || {}).map(([code, value]) => code + ' ' + [value.launch_price, value.current_price, value.estimated_after_price].map(item => item == null ? '—' : Number(item).toFixed(2)).join(' / ')).join('；') || '暂无当前价' },
        { title: '当前累计', dataIndex: 'current', render: pricingPercent },
        { title: '生效日已有累计', dataIndex: 'before', render: pricingPercent },
        { title: '本次降幅', render: () => pricingPercent(preview.payload.discount_percent) },
        { title: '登记后累计', dataIndex: 'after', render: pricingPercent },
      ]} />
      <Button onClick={() => { requestId.current = crypto.randomUUID(); setPreview(null); }}>返回修改</Button>
    </>}
  </Modal>;
}

const statusNames: Record<string, string> = { pending: '待生效', active: '已生效', ended: '已结束', voided: '已作废', historical: '历史快照（不代表当前生效）' };
export function PricingBatches({ refreshToken, onRegister }: {
  refreshToken: number; onRegister: () => void;
}) {
  const [rows, setRows] = useState<PricingBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.pricingBatches(controller.signal).then(result => setRows(result.rows)).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '长期调价批次加载失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshToken]);
  return <Card title="长期调价批次" extra={<Button onClick={onRegister}>登记调价 / 促销</Button>}>
    {error && <Alert type="error" message={error} />}
    <Table<PricingBatch>
      rowKey="batch_id"
      size="small"
      loading={loading}
      dataSource={rows}
      pagination={false}
      columns={[
        { title: '批次名称', dataIndex: 'batch_name' },
        { title: '本次降幅', dataIndex: 'discount_percent', width: 110, render: value => '-' + pricingPercent(value) },
        { title: '生效日期', dataIndex: 'effective_date', width: 130 },
        { title: 'SKU 数', dataIndex: 'sku_count', width: 100, render: value => value.toLocaleString('zh-CN') },
        { title: '状态', dataIndex: 'status', width: 100, render: value => <Tag color={value === 'active' ? 'green' : value === 'pending' ? 'gold' : 'default'}>{statusNames[value]}</Tag> },
      ]}
      expandable={{
        expandedRowRender: batch => <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 30 }}
          dataSource={batch.events}
          columns={[
            { title: 'SKU', dataIndex: 'sku' },
            { title: '本次降幅', dataIndex: 'discount_percent', render: value => '-' + pricingPercent(value) },
            { title: '当前累计调价', dataIndex: 'cumulative_discount', render: pricingPercent },
            { title: '状态', dataIndex: 'status', render: value => statusNames[value] },
          ]}
        />,
        rowExpandable: batch => batch.events.length > 0,
      }}
    />
  </Card>;
}

export function PricingHistory({ refreshToken, onRefresh, onRegister }: {
  refreshToken: number; onRefresh: () => void; onRegister: () => void;
}) {
  const [rows, setRows] = useState<PricingHistoryRow[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [voidRow, setVoidRow] = useState<PricingHistoryRow | null>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.pricingHistory(search, controller.signal).then(r => setRows(r.rows)).catch(e => {
      if (!controller.signal.aborted) setError(e.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshToken, search]);
  return <Card title="SKU 历史">
    <Space wrap><Input.Search placeholder="搜索 SKU" onSearch={setSearch} allowClear /><Button onClick={onRegister}>批量登记调价 / 促销</Button></Space>
    {error && <Alert type="error" message={error} />}
    <Table rowKey={r => r.type + ':' + r.id} size="small" loading={loading} dataSource={rows} scroll={{ x: 1050 }} pagination={{ pageSize: 30 }} columns={[
      { title: 'SKU', dataIndex: 'sku', width: 190 },
      { title: '类型', dataIndex: 'type', render: v => <Tag>{v === 'adjustment' ? '长期调价' : v === 'snapshot' ? '限时历史快照' : '限时促销'}</Tag> },
      { title: '批次 / 活动名称', dataIndex: 'name', width: 220 },
      { title: '本次降幅 / 额外优惠', dataIndex: 'discount_percent', render: v => '-' + pricingPercent(v) },
      { title: '当前累计调价', dataIndex: 'cumulative_discount', render: pricingPercent },
      { title: '生效 / 开始日期', dataIndex: 'start_date', sorter: (a,b) => a.start_date.localeCompare(b.start_date) },
      { title: '结束日期', dataIndex: 'end_date', render: v => v || '-' },
      { title: '状态', dataIndex: 'status', render: v => statusNames[v] },
      { title: '审计 / 纠错', render: (_,r) => <Space direction="vertical">
        {r.migration_source && <Typography.Text type="secondary">历史活动迁入</Typography.Text>}
        {r.void_reason || (r.type === 'adjustment' && r.status !== 'voided' && <Button danger size="small" onClick={() => { setVoidRow(r); setReason(''); }}>作废</Button>)}
      </Space> },
    ]} />
    <Modal title="作废调价记录" open={!!voidRow} confirmLoading={saving} onCancel={() => { if (!saving) setVoidRow(null); }} onOk={async () => {
      if (!voidRow || saving || !reason.trim()) return;
      setSaving(true);
      try { await api.voidAdjustment(voidRow.id, reason); setVoidRow(null); onRefresh(); }
      catch (e) { message.error(e instanceof Error ? e.message : '作废失败'); }
      finally { setSaving(false); }
    }}>
      <Alert type="warning" message="作废仅纠正系统记录，不恢复平台价格。作废后累计降幅会重新计算。" />
      <Input.TextArea value={reason} onChange={e => setReason(e.target.value)} placeholder="必填：误登记原因" maxLength={500} />
    </Modal>
  </Card>;
}
