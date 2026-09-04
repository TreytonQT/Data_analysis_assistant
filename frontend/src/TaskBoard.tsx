import React, { useCallback, useEffect, useRef, useState } from 'react';
import dayjs, { Dayjs } from 'dayjs';
import { Alert, Badge, Button, Card, DatePicker, Form, Input, Modal, Select, Space, Spin, Tag, Typography, Upload } from 'antd';
import { feedbackMessage as message, downloadWithFeedback } from './feedback';
import { HolderOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { api, type Status, type Task, type TaskInput } from './api';

const statusMeta: Record<Status, { label: string; color: string }> = {
  todo: { label: '待办', color: '#3b82f6' }, current: { label: '当前待办', color: '#fb7185' }, in_progress: { label: '进行中', color: '#f59e0b' }, snoozed: { label: '已搁置', color: '#94a3b8' }, completed: { label: '已完成', color: '#34c38f' },
};

function localDate(value?: string | null) { return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '未设置'; }
function toIso(value?: Dayjs | null) { return value ? value.toISOString() : null; }

type TaskFormValues = Omit<TaskInput, 'due_at' | 'remind_at'> & { remind_at: Dayjs | null };

function taskFormValues(task?: Task): TaskFormValues {
  if (!task) {
    return { title: '', notes: '', status: 'todo', remind_at: null, recurrence_type: 'none', recurrence_days: [] };
  }
  const reminder = task.remind_at ?? task.due_at;
  return {
    title: task.title,
    notes: task.notes ?? '',
    status: task.status,
    remind_at: reminder ? dayjs(reminder) : null,
    recurrence_type: task.recurrence_type,
    recurrence_days: [...task.recurrence_days],
  };
}

function TaskModal({ task, open, onClose, onSaved }: { task?: Task; open: boolean; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<TaskFormValues>();
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue(taskFormValues(task));
  }, [open, task, form]);

  const clearAndClose = () => {
    form.resetFields();
    onClose();
  };

  const cancel = () => {
    if (savingRef.current) return;
    clearAndClose();
  };

  const submit = async () => {
    if (savingRef.current) return;
    savingRef.current = true;

    let values: TaskFormValues;
    try {
      values = await form.validateFields();
    } catch {
      savingRef.current = false;
      return;
    }

    setSaving(true);
    try {
      const reminder = toIso(values.remind_at);
      const payload: TaskInput = {
        ...values,
        notes: values.notes ?? '',
        status: task ? task.status : values.status,
        recurrence_days: values.recurrence_type === 'none' ? [] : values.recurrence_days ?? [],
        due_at: reminder,
        remind_at: reminder,
      };
      if (task) {
        await api.updateTask(task.id, payload);
        if (values.status !== task.status) await api.transition(task.id, values.status);
      } else {
        await api.createTask(payload);
      }
      message.success(task ? `任务“${task.title}”已更新` : `任务“${values.title}”已创建`);
      onSaved();
      clearAndClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return <Modal title={task ? '编辑任务' : '新建任务'} open={open} onCancel={cancel} onOk={submit} confirmLoading={saving} okText="保存" closable={!saving} maskClosable={!saving} keyboard={!saving} cancelButtonProps={{ disabled: saving }} destroyOnHidden>
    <Form form={form} layout="vertical"><Form.Item name="title" label="任务标题" rules={[{ required: true, message: '请输入任务标题' }]}><Input autoFocus placeholder="例如：检查补货建议" /></Form.Item><Form.Item name="notes" label="备注"><Input.TextArea rows={4} placeholder="补充任务说明、链接或清单" /></Form.Item><Space size="large" wrap><Form.Item name="status" label="状态"><Select options={(Object.keys(statusMeta) as Status[]).map(value => ({ value, label: statusMeta[value].label }))} /></Form.Item><Form.Item name="remind_at" label="提醒时间"><DatePicker showTime /></Form.Item></Space><Space size="large" wrap><Form.Item name="recurrence_type" label="重复"><Select options={[['none', '不重复'], ['daily', '每天'], ['weekly', '每周'], ['monthly', '每月']].map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item noStyle shouldUpdate={(prev, next) => prev.recurrence_type !== next.recurrence_type}>{({ getFieldValue }) => getFieldValue('recurrence_type') !== 'none' ? <Form.Item name="recurrence_days" label={getFieldValue('recurrence_type') === 'weekly' ? '星期（0 为周一）' : '日期'}><Select mode="multiple" style={{ minWidth: 180 }} options={(getFieldValue('recurrence_type') === 'weekly' ? ['周一','周二','周三','周四','周五','周六','周日'] : Array.from({length:31}, (_,i) => `${i+1} 日`)).map((label, value) => ({ value: getFieldValue('recurrence_type') === 'weekly' ? value : value + 1, label }))} /></Form.Item> : null}</Form.Item></Space></Form>
  </Modal>;
}

export default function TaskBoard({ active, onTasksChanged }: { active: boolean; onTasksChanged: () => Promise<void> | void }) {
  const [tasks, setTasks] = useState<Task[]>([]); const [search, setSearch] = useState(''); const [loading, setLoading] = useState(false); const [loadError, setLoadError] = useState(''); const [modal, setModal] = useState<{ open: boolean; task?: Task }>({ open: false }); const [deleteCandidate, setDeleteCandidate] = useState<Task>(); const [deleting, setDeleting] = useState(false); const [draggedTask, setDraggedTask] = useState<Task>(); const [dropTarget, setDropTarget] = useState<string>();
  const draggedTaskRef = useRef<Task | undefined>(undefined);
  const pointerDropRef = useRef<{ status: Status; beforeId: string | null } | undefined>(undefined);
  const refresh = useCallback(async (showLoading = false) => { if (!active) return false; if (showLoading) setLoading(true); try { const rows = await api.tasks(search); setTasks(rows); setLoadError(''); await onTasksChanged(); return true; } catch (error) { const detail = error instanceof Error ? error.message : '加载任务失败'; setLoadError(detail); if (!showLoading) message.error(detail); return false; } finally { if (showLoading) setLoading(false); } }, [active, onTasksChanged, search]);
  useEffect(() => { if (!active) return undefined; void refresh(true); const timer = window.setInterval(() => { void refresh(); }, 60000); return () => clearInterval(timer); }, [active, refresh]);
  const move = async (task: Task, status: Status) => { const operationKey = `task-status-${task.id}`; try { await api.transition(task.id, status); const refreshed = await refresh(); message.success({ key: operationKey, content: `任务“${task.title}”已${statusMeta[status].label}` }); if (refreshed === false) message.warning({ key: operationKey, content: `任务“${task.title}”已更新，但列表刷新失败`, duration: 6 }); } catch (error) { const detail = error instanceof Error ? error.message : '状态更新失败'; message.error({ key: operationKey, content: `任务“${task.title}”状态更新失败：${detail}`, duration: 6 }); } };
  const dropTask = async (status: Status, beforeId: string | null) => {
    const original = draggedTaskRef.current;
    if (!original || original.id === beforeId) return;
    draggedTaskRef.current = undefined;
    setDraggedTask(undefined); setDropTarget(undefined);
    try {
      if (original.status !== status) await api.transition(original.id, status);
      await api.moveTask(original.id, status, beforeId);
      await refresh();
    } catch (error) { const detail = error instanceof Error ? error.message : '调整顺序失败'; message.error(`任务“${original.title}”调整顺序失败：${detail}`); await refresh(); }
  };
  const cardDropPosition = (status: Status, hoveredId: string, after: boolean) => {
    const original = draggedTaskRef.current;
    if (!original || original.id === hoveredId) return undefined;
    const destination = tasks.filter(task => task.status === status && task.id !== original.id);
    const hoveredIndex = destination.findIndex(task => task.id === hoveredId);
    if (hoveredIndex < 0) return undefined;
    return after ? destination[hoveredIndex + 1]?.id ?? null : hoveredId;
  };
  const updatePointerDrop = (clientX: number, clientY: number) => {
    const element = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
    const card = element?.closest<HTMLElement>('.task-card');
    if (card?.dataset.taskId && card.dataset.status) {
      const status = card.dataset.status as Status;
      const rect = card.getBoundingClientRect();
      const after = clientY > rect.top + rect.height / 2;
      const beforeId = cardDropPosition(status, card.dataset.taskId, after);
      if (beforeId !== undefined) {
        pointerDropRef.current = { status, beforeId };
        setDropTarget(`${card.dataset.taskId}:${after ? 'after' : 'before'}`);
      } else {
        pointerDropRef.current = undefined;
        setDropTarget(undefined);
      }
      return;
    }
    const column = element?.closest<HTMLElement>('.task-column');
    if (column?.dataset.status) {
      const status = column.dataset.status as Status;
      pointerDropRef.current = { status, beforeId: null };
      setDropTarget(`${status}:end`);
    }
  };
  const finishPointerDrag = (event: React.PointerEvent<HTMLSpanElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const destination = pointerDropRef.current;
    pointerDropRef.current = undefined;
    if (destination) void dropTask(destination.status, destination.beforeId);
    else { draggedTaskRef.current = undefined; setDraggedTask(undefined); setDropTarget(undefined); }
  };
  const cancelPointerDrag = (event: React.PointerEvent<HTMLSpanElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    pointerDropRef.current = undefined; draggedTaskRef.current = undefined; setDraggedTask(undefined); setDropTarget(undefined);
  };
  const confirmDelete = async () => { if (!deleteCandidate) return; const title = deleteCandidate.title; const operationKey = `task-delete-${deleteCandidate.id}`; setDeleting(true); try { await api.deleteTask(deleteCandidate.id); const refreshed = await refresh(); setDeleteCandidate(undefined); message.success({ key: operationKey, content: `任务“${title}”已删除` }); if (refreshed === false) message.warning({ key: operationKey, content: `任务“${title}”已删除，但列表刷新失败`, duration: 6 }); } catch (error) { message.error({ key: operationKey, content: error instanceof Error ? error.message : `任务“${title}”删除失败`, duration: 6 }); } finally { setDeleting(false); } };
  const actions = (task: Task) => <Space wrap size={4}><Button size="small" onClick={() => setModal({ open: true, task })}>编辑</Button>{task.status === 'current' && <Button size="small" onClick={() => move(task, 'in_progress')}>开始</Button>}{task.status === 'snoozed' && <Button size="small" onClick={() => move(task, 'current')}>恢复</Button>}{task.status !== 'completed' && <Button size="small" type="primary" onClick={() => move(task, 'completed')}>完成</Button>}{task.status !== 'snoozed' && task.status !== 'completed' && <Button size="small" onClick={() => move(task, 'snoozed')}>搁置</Button>}{task.status === 'completed' && <Button size="small" onClick={() => move(task, 'current')}>重开</Button>}<Button size="small" danger onClick={() => setDeleteCandidate(task)}>删除</Button></Space>;
  const importer: UploadProps = { accept: '.json', showUploadList: false, beforeUpload: async file => { try { const text = await file.text(); const parsed = JSON.parse(text); const payload = Array.isArray(parsed) ? parsed : parsed.tasks; if (!Array.isArray(payload)) throw new Error('JSON 文件必须是任务数组'); await api.importTasks(payload.map(({ id, created_at, updated_at, is_overdue, ...task }) => task)); message.success({ key: 'task-import', content: `已导入 ${payload.length} 项任务` }); const refreshed = await refresh(); if (refreshed === false) message.warning({ key: 'task-import', content: `已导入 ${payload.length} 项任务，但列表刷新失败`, duration: 6 }); } catch (error) { message.error(error instanceof Error ? error.message : '导入失败'); } return false; } };
  return <>
    <div className="task-drawer-toolbar"><div><Typography.Text strong>全部待办</Typography.Text><Typography.Text type="secondary">集中管理工作任务、重复计划与提醒</Typography.Text></div><Space wrap className="task-drawer-actions"><Input.Search placeholder="搜索任务或备注" allowClear onSearch={setSearch} style={{ width: 280 }} /><Button icon={<ReloadOutlined />} onClick={() => void (async () => { const refreshed = await refresh(true); if (refreshed !== false) message.success('待办列表已刷新'); else message.error('待办列表刷新失败'); })()}>刷新</Button><Button href="/api/tasks/export.csv" onClick={event => { event.preventDefault(); void downloadWithFeedback('/api/tasks/export.csv', 'tasks.csv', '待办 CSV'); }}>导出 CSV</Button><Upload {...importer}><Button>导入 JSON</Button></Upload><Button type="primary" icon={<PlusOutlined />} onClick={() => setModal({ open: true })}>新增任务</Button></Space></div>
    {loadError && <Alert className="task-load-error" type="error" showIcon message="待办加载失败" description={loadError} action={<Button size="small" onClick={() => void refresh(true)}>重新加载</Button>} />}
    <Spin spinning={loading} wrapperClassName="task-board-spinner"><div className="task-board">{(Object.keys(statusMeta) as Status[]).map(status => {
      const rows = tasks.filter(task => task.status === status);
      return <section className={`task-column ${dropTarget === `${status}:end` ? 'task-drop-target' : ''}`} data-status={status} key={status}>
        <div className="task-column-title"><Badge color={statusMeta[status].color} text={statusMeta[status].label} /><Badge count={rows.length} showZero color="#e8eef8" styles={{ indicator: { color: '#406080' } }} /></div>
        {rows.map(task => <Card className={`task-card ${task.is_overdue ? 'task-overdue' : ''} ${draggedTask?.id === task.id ? 'task-dragging' : ''} ${dropTarget === `${task.id}:before` ? 'task-drop-before' : ''} ${dropTarget === `${task.id}:after` ? 'task-drop-after' : ''}`} data-task-id={task.id} data-status={status} key={task.id} size="small">
          <div className="task-card-heading"><Typography.Text strong>{task.title}</Typography.Text><span className="task-drag-handle" onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); draggedTaskRef.current = task; pointerDropRef.current = undefined; setDraggedTask(task); }} onPointerMove={event => { if (draggedTaskRef.current?.id === task.id) updatePointerDrop(event.clientX, event.clientY); }} onPointerUp={finishPointerDrag} onPointerCancel={cancelPointerDrag} title="拖拽调整顺序或状态"><HolderOutlined /></span></div>
          {task.notes && <Typography.Paragraph className="task-notes" ellipsis={{ rows: 3, expandable: true }}>{task.notes}</Typography.Paragraph>}
          <Space wrap size={4}><Tag>{task.recurrence_type === 'none' ? '不重复' : task.recurrence_type === 'daily' ? '每天' : task.recurrence_type === 'weekly' ? '每周' : '每月'}</Tag>{task.remind_at && <Tag color={task.is_overdue ? 'error' : 'blue'}>提醒 {localDate(task.remind_at)}</Tag>}{task.status === 'completed' && task.next_reminder_at && task.recurrence_type !== 'none' && <Tag color="cyan">下次 {localDate(task.next_reminder_at)}</Tag>}</Space>
          <div className="task-actions">{actions(task)}</div>
        </Card>)}
        {!rows.length && <div className="empty-column">暂无任务</div>}
      </section>;
    })}</div></Spin>
    <TaskModal open={modal.open} task={modal.task} onClose={() => setModal({ open: false })} onSaved={() => { void refresh(); }} />
    <Modal title="确认删除待办？" open={Boolean(deleteCandidate)} onCancel={() => setDeleteCandidate(undefined)} onOk={confirmDelete} confirmLoading={deleting} okText="确认删除" okButtonProps={{ danger: true }} cancelText="取消">“{deleteCandidate?.title}”删除后无法恢复。</Modal>
  </>;
}
