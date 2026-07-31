import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Card, Input, Popconfirm, Select, Space, Spin, Table, Tabs, Tag, Typography, Upload, message } from 'antd';
import { DeleteOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined, SaveOutlined, UploadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { api, apiErrorMessage, type ConfigData } from './api';

type ConfigRow = Record<string, unknown> & { _rowId: string };
type EditableConfig = Omit<ConfigData, 'rows'> & { rows: ConfigRow[] };

let fallbackRowId = 0;
function nextRowId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  fallbackRowId += 1;
  return `config-row-${Date.now()}-${fallbackRowId}`;
}

function attachRowIds(rows: Record<string, unknown>[], previous: ConfigRow[] = []): ConfigRow[] {
  return rows.map((row, index) => {
    const { _rowId: _ignored, ...values } = row;
    return { ...values, _rowId: previous[index]?._rowId || nextRowId() };
  });
}

function serializableRows(rows: ConfigRow[]) {
  return rows.map(({ _rowId: _ignored, ...row }) => row);
}

function latestConfigTime(configs: ConfigData[]) {
  const timestamps = configs.map(config => config.updated_at).filter((value): value is string => Boolean(value));
  if (!timestamps.length) return '';
  const latest = timestamps.reduce((current, value) => new Date(value).getTime() > new Date(current).getTime() ? value : current);
  const date = new Date(latest);
  return Number.isNaN(date.getTime()) ? latest : date.toLocaleString('zh-CN', { hour12: false });
}

function cellEditor(
  rowId: string,
  column: string,
  value: unknown,
  disabled: boolean,
  update: (rowId: string, column: string, value: unknown) => void,
) {
  if (column === '是否启用' || column === '是否补货') {
    const enabled = value === true || ['1', 'true', 'yes', 'y', '是', '启用'].includes(String(value || '').trim().toLowerCase());
    return <Select disabled={disabled} value={enabled ? '是' : '否'} style={{ width: 90 }} options={[{ value: '是', label: '是' }, { value: '否', label: '否' }]} onChange={next => update(rowId, column, next)} />;
  }
  if (column === '店铺类型') return <Select disabled={disabled} allowClear value={value ? String(value) : undefined} style={{ minWidth: 110 }} options={['中企', '本土', '其他'].map(item => ({ value: item, label: item }))} onChange={next => update(rowId, column, next || '')} />;
  if (column === '公式') return <Input.TextArea disabled={disabled} value={String(value ?? '')} autoSize={{ minRows: 1, maxRows: 4 }} onChange={event => update(rowId, column, event.target.value)} />;
  return <Input disabled={disabled} value={String(value ?? '')} onChange={event => update(rowId, column, event.target.value)} />;
}

export default function ConfigCenter({ active: pageActive = true, refreshVersion = 0 }: { active?: boolean; refreshVersion?: number }) {
  const [configs, setConfigs] = useState<EditableConfig[]>([]);
  const [active, setActive] = useState('metrics_config');
  const [saving, setSaving] = useState('');
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');
  const seenRefreshVersion = useRef(refreshVersion);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await api.configs();
      setConfigs(result.configs.map(config => ({ ...config, rows: attachRowIds(config.rows) })));
      setDirty(new Set());
      setActive(current => result.configs.some(item => item.name === current) ? current : result.configs[0]?.name || '');
      setLastUpdated(latestConfigTime(result.configs));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!pageActive || seenRefreshVersion.current === refreshVersion) return;
    seenRefreshVersion.current = refreshVersion;
    void refresh();
  }, [pageActive, refresh, refreshVersion]);

  const markDirty = (name: string) => setDirty(current => {
    const next = new Set(current); next.add(name); return next;
  });
  const clearDirty = (name: string) => setDirty(current => {
    const next = new Set(current); next.delete(name); return next;
  });
  const updateCell = (name: string, rowId: string, column: string, value: unknown) => {
    setConfigs(current => current.map(config => config.name !== name ? config : { ...config, rows: config.rows.map(row => row._rowId === rowId ? { ...row, [column]: value } : row) }));
    markDirty(name);
  };
  const addRow = (config: EditableConfig) => {
    const row = { ...Object.fromEntries(config.columns.map(column => [column, ''])), _rowId: nextRowId() } as ConfigRow;
    setConfigs(current => current.map(item => item.name === config.name ? { ...item, rows: [...item.rows, row] } : item));
    markDirty(config.name);
  };
  const deleteRow = (name: string, rowId: string) => {
    setConfigs(current => current.map(config => config.name !== name ? config : { ...config, rows: config.rows.filter(row => row._rowId !== rowId) }));
    markDirty(name);
  };
  const save = async (config: EditableConfig) => {
    if (saving) return;
    setSaving(config.name);
    setError('');
    try {
      const result = await api.saveConfig(config.name, serializableRows(config.rows));
      setConfigs(current => current.map(item => item.name === config.name ? { ...item, rows: attachRowIds(result.rows, config.rows) } : item));
      clearDirty(config.name);
      setLastUpdated(result.updated_at ? new Date(result.updated_at).toLocaleString('zh-CN', { hour12: false }) : new Date().toLocaleString('zh-CN', { hour12: false }));
      message.success(`${config.title}已校验并保存`);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存失败');
    } finally {
      setSaving('');
    }
  };
  const importer = (config: EditableConfig): UploadProps => ({
    accept: '.csv,.xlsx', showUploadList: false, disabled: Boolean(saving),
    beforeUpload: async file => {
      if (saving) return false;
      setSaving(config.name);
      setError('');
      try {
        const body = new FormData(); body.append('file', file);
        const response = await fetch(`/api/config/${config.name}/upload`, { method: 'POST', body });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(apiErrorMessage(result, '导入失败'));
        setConfigs(current => current.map(item => item.name === config.name ? { ...item, rows: attachRowIds(result.rows) } : item));
        clearDirty(config.name);
        setLastUpdated(result.updated_at ? new Date(result.updated_at).toLocaleString('zh-CN', { hour12: false }) : new Date().toLocaleString('zh-CN', { hour12: false }));
        message.success(`${config.title}已导入并保存`);
      } catch (importError) {
        setError(importError instanceof Error ? importError.message : '导入失败');
      } finally {
        setSaving('');
      }
      return false;
    },
  });

  const hasDirty = dirty.size > 0;
  const items = useMemo(() => configs.map(config => {
    const locked = saving === config.name;
    const changed = dirty.has(config.name);
    return {
      key: config.name,
      label: <Space size={6}><span>{config.title}</span>{changed && <Tag color="gold">未保存</Tag>}</Space>,
      children: <Card data-testid={`config-${config.name}`}>
        <Typography.Paragraph type="secondary">{config.description}</Typography.Paragraph>
        <Space wrap className="config-actions">
          <Button disabled={locked || Boolean(saving)} icon={<PlusOutlined />} onClick={() => addRow(config)}>新增一行</Button>
          <Upload {...importer(config)}><Button disabled={locked || Boolean(saving)} loading={locked} icon={<UploadOutlined />}>导入 CSV/XLSX</Button></Upload>
          <Button disabled={Boolean(saving)} icon={<DownloadOutlined />} href={`/api/config/${config.name}/download`}>下载当前 CSV</Button>
          <Button type="primary" disabled={!changed || Boolean(saving && !locked)} loading={locked} icon={<SaveOutlined />} onClick={() => void save(config)}>校验并保存</Button>
          {changed && <Typography.Text type="warning">当前修改仅保存在浏览器，校验通过后才会写入文件。</Typography.Text>}
        </Space>
        <Table
          rowKey="_rowId"
          size="small"
          pagination={{ pageSize: 15, showSizeChanger: true, showTotal: total => `共 ${total} 行` }}
          scroll={{ x: 'max-content' }}
          dataSource={config.rows}
          locale={{ emptyText: '暂无配置，点击“新增一行”开始编辑' }}
          columns={[
            ...config.columns.map(column => ({
              title: column, dataIndex: column, key: column, width: column === '公式' ? 440 : 160,
              render: (value: unknown, row: ConfigRow) => cellEditor(row._rowId, column, value, locked, (rowId, key, next) => updateCell(config.name, rowId, key, next)),
            })),
            { title: '操作', key: 'action', fixed: 'right' as const, width: 76, render: (_: unknown, row: ConfigRow) => <Popconfirm disabled={locked} title="确定删除这一行吗？" onConfirm={() => deleteRow(config.name, row._rowId)}><Button disabled={locked} size="small" danger icon={<DeleteOutlined />} /></Popconfirm> },
          ]}
        />
      </Card>,
    };
  }), [configs, dirty, saving]);

  const reloadButton = <Button disabled={loading || Boolean(saving)} loading={loading} icon={<ReloadOutlined />} onClick={() => { if (!hasDirty) void refresh(); }}>重新载入</Button>;
  return <>
    <div className="page-heading">
      <div><Typography.Title level={2}>配置中心</Typography.Title><Typography.Text type="secondary">所有配置均在保存前校验字段、数值和业务规则；库存覆盖规则会校验重量区间完整且不重叠。{lastUpdated && ` · 数据更新时间 ${lastUpdated}`}</Typography.Text></div>
      {hasDirty ? <Popconfirm title="放弃全部未保存修改并重新载入吗？" onConfirm={() => void refresh()}>{reloadButton}</Popconfirm> : reloadButton}
    </div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="配置操作失败" description={error} action={hasDirty ? <Button size="small" onClick={() => setError('')}>保留本地修改</Button> : <Button size="small" onClick={() => void refresh()}>重新加载</Button>} />}
    <Spin spinning={loading} tip="正在读取配置…"><div className="page-loading-min-height"><Tabs activeKey={active} onChange={setActive} items={items} tabPosition="top" /></div></Spin>
  </>;
}
