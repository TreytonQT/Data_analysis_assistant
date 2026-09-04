import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Modal, Popconfirm, Space, Spin, Table, Tag, Typography, Upload } from 'antd';
import { feedbackMessage as message, downloadWithFeedback } from './feedback';
import { DeleteOutlined, DownloadOutlined, EyeOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import type { TableProps, UploadProps } from 'antd';
import { api, apiErrorMessage, type ReportsResponse, type SourceRecord } from './api';

export type UploadFrequencyTab = 'daily' | 'weekly' | 'monthly';

export function uploadFrequencyTabFromSearch(search: string): UploadFrequencyTab {
  const tab = new URLSearchParams(search).get('tab');
  return tab === 'weekly' || tab === 'monthly' ? tab : 'daily';
}

const sourceDefinitions = [
  { key: 'operational_sales', frequency: 'daily', title: '运营原始表', accept: '.xls,.xlsx', description: '个人销量、库存、库龄、产品和补货分析的核心数据源' },
  { key: 'gross_profit', frequency: 'daily', title: '毛利原始表', accept: '.csv,.xls,.xlsx', description: '产品毛利率、广告费和异常原因分析' },
  { key: 'rating', frequency: 'weekly', title: 'Rating', accept: '.xls,.xlsx', description: 'ASIN 各站点评分和评价数量' },
  { key: 'sales_volume_detail', frequency: 'daily', title: '销量明细', accept: '.csv', description: '部门监控的销量明细数据' },
  { key: 'sales_amount_detail', frequency: 'daily', title: '销售额明细', accept: '.csv', description: '部门监控的销售额明细数据' },
  { key: 'sku_image_map', frequency: 'monthly', title: 'SKU图片映射表', accept: '.xls,.xlsx', description: '按库存SKU和虚拟SKU关联补货、滞销和产品矩阵中的图片' },
] as const;
const { Dragger } = Upload;

function fileSize(value: unknown) {
  const bytes = Number(value);
  return Number.isFinite(bytes) ? `${(bytes / 1024).toFixed(1)} KB` : '-';
}

function latestUploadTime(data: ReportsResponse) {
  const rows = [...data.reports, ...Object.values(data.sources).flatMap(source => source.records || [])];
  const timestamps = rows.map(row => String(row['上传时间'] || '')).filter(Boolean).sort();
  return timestamps.at(-1) || '';
}

export default function UploadCenter({ active = true, routeVersion = 0, refreshVersion = 0 }: { active?: boolean; routeVersion?: number; refreshVersion?: number }) {
  const [data, setData] = useState<ReportsResponse>({ reports: [], sources: {} });
  const [initialLoading, setInitialLoading] = useState(true);
  const [pending, setPending] = useState<Record<string, number>>({});
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');
  const [preview, setPreview] = useState<{ title: string; columns: string[]; rows: Record<string, unknown>[]; total: number }>();
  const [tab, setTab] = useState<UploadFrequencyTab>(() => uploadFrequencyTabFromSearch(window.location.search));
  const seenRefreshVersion = useRef(refreshVersion);
  const seenRouteVersion = useRef(routeVersion);

  const begin = (key: string) => setPending(current => ({ ...current, [key]: (current[key] || 0) + 1 }));
  const end = (key: string) => setPending(current => {
    const next = { ...current };
    if ((next[key] || 0) <= 1) delete next[key]; else next[key] -= 1;
    return next;
  });
  const isPending = (key: string) => Boolean(pending[key]);

  const refresh = useCallback(async (showLoading = true, resetError = true) => {
    if (showLoading) setInitialLoading(true);
    if (resetError) setError('');
    try {
      const result = await api.reports();
      setData(result);
      setLastUpdated(latestUploadTime(result));
      return true;
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取上传记录失败');
      return false;
    } finally {
      if (showLoading) setInitialLoading(false);
    }
  }, []);
  const manualRefresh = async () => {
    const refreshed = await refresh();
    if (refreshed) message.success('上传记录已刷新');
    else message.error('上传记录刷新失败');
  };
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!active || seenRefreshVersion.current === refreshVersion) return;
    seenRefreshVersion.current = refreshVersion;
    void refresh(false);
  }, [active, refresh, refreshVersion]);
  useEffect(() => {
    if (!active || seenRouteVersion.current === routeVersion) return;
    seenRouteVersion.current = routeVersion;
    setTab(uploadFrequencyTabFromSearch(window.location.search));
  }, [active, routeVersion]);
  useEffect(() => {
    const onPopState = () => {
      const page = new URLSearchParams(window.location.search).get('page') || 'overview';
      if (active && page === 'uploads') setTab(uploadFrequencyTabFromSearch(window.location.search));
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [active]);

  const uploader = (key: string, url: string, multiple = false, accept?: string): UploadProps => ({
    accept, multiple, showUploadList: false,
    beforeUpload: async (file, fileList) => {
      if (multiple && file.uid !== fileList[0]?.uid) return false;
      const operationKey = `upload-${key}`;
      begin(operationKey);
      setError('');
      const selectedFiles = multiple ? fileList : [file];
      const displayName = selectedFiles.length > 1 ? `${selectedFiles.length} 个文件` : file.name;
      const noticeKey = `upload-${key}-${file.uid}`;
      message.loading({ content: `正在上传 ${displayName}…`, key: noticeKey, duration: 0 });
      try {
        const body = new FormData();
        selectedFiles.forEach(selected => body.append(multiple ? 'files' : 'file', selected));
        const response = await fetch(url, { method: 'POST', body });
        const result = await response.json().catch(() => null);
        if (!response.ok) throw new Error(apiErrorMessage(result, '上传失败'));
        const warnings = Array.isArray(result?.warnings)
          ? result.warnings.filter((warning: unknown): warning is string => typeof warning === 'string' && Boolean(warning))
          : [];
        if (warnings.length) {
          message.warning({ content: `${displayName} 上传完成，但有 ${warnings.length} 项需要注意：${warnings.slice(0, 2).join('；')}`, key: noticeKey, duration: 6 });
        } else {
          message.success({ content: `${displayName} 上传成功，已整批校验并保存`, key: noticeKey, duration: 2.5 });
        }
        const refreshed = await refresh(false, false);
        if (!refreshed) message.warning({ content: `${displayName} 上传已成功，但页面刷新失败`, key: noticeKey, duration: 6 });
      } catch (uploadError) {
        const detail = uploadError instanceof Error ? `${displayName} 上传失败：${uploadError.message}` : `${displayName} 上传失败`;
        setError(detail);
        message.error({ content: detail, key: noticeKey, duration: 6 });
      } finally {
        end(operationKey);
      }
      return false;
    },
  });

  const showPreview = async (key: string) => {
    const operationKey = `preview-${key}`;
    begin(operationKey); setError('');
    try { setPreview(await api.previewSource(key)); }
    catch (previewError) { const detail = previewError instanceof Error ? previewError.message : '预览失败'; setError(detail); message.error(`预览${key}失败：${detail}`); }
    finally { end(operationKey); }
  };
  const deleteSource = async (key: string) => {
    const operationKey = `delete-${key}`;
    begin(operationKey); setError('');
    try { await api.deleteSource(key); message.success({ key: operationKey, content: `${sourceDefinitions.find(item => item.key === key)?.title || key}已删除` }); const refreshed = await refresh(false, false); if (!refreshed) message.warning({ key: operationKey, content: '数据源已删除，但页面刷新失败', duration: 6 }); }
    catch (deleteError) { const detail = deleteError instanceof Error ? deleteError.message : '删除失败'; setError(detail); message.error(`${key}删除失败：${detail}`); }
    finally { end(operationKey); }
  };
  const deleteReport = async (month: string) => {
    const operationKey = `delete-report-${month}`;
    begin(operationKey); setError('');
    try { await api.deleteReport(month); message.success({ key: operationKey, content: `${month}业绩报表已删除` }); const refreshed = await refresh(false, false); if (!refreshed) message.warning({ key: operationKey, content: `${month}业绩报表已删除，但页面刷新失败`, duration: 6 }); }
    catch (deleteError) { const detail = deleteError instanceof Error ? deleteError.message : '删除失败'; setError(detail); message.error(`${month}业绩报表删除失败：${detail}`); }
    finally { end(operationKey); }
  };
  const deleteSalesHistory = async () => {
    const operationKey = 'delete-sales-history';
    begin(operationKey); setError('');
    try { await api.deleteSalesHistory(); message.success({ key: operationKey, content: '往月销量原始表已清空' }); const refreshed = await refresh(false, false); if (!refreshed) message.warning({ key: operationKey, content: '往月销量原始表已清空，但页面刷新失败', duration: 6 }); }
    catch (deleteError) { const detail = deleteError instanceof Error ? deleteError.message : '删除失败'; setError(detail); message.error(`往月销量原始表清空失败：${detail}`); }
    finally { end(operationKey); }
  };

  const reportColumns: TableProps<SourceRecord>['columns'] = [
    { title: '月份', dataIndex: '月份' }, { title: '原始文件名', dataIndex: '原始文件名', ellipsis: true },
    { title: '上传时间', dataIndex: '上传时间' }, { title: '大小', dataIndex: '文件大小', render: fileSize },
    { title: '操作', render: (_, row) => {
      const month = String(row['月份']); const deleting = isPending(`delete-report-${month}`);
      return <Space><Button disabled={deleting} size="small" icon={<DownloadOutlined />} href={`/api/reports/performance/${encodeURIComponent(month)}/download`} onClick={event => { event.preventDefault(); void downloadWithFeedback(`/api/reports/performance/${encodeURIComponent(month)}/download`, `${month}.csv`, `${month}业绩报表`); }}>下载</Button><Popconfirm title="确定删除该月份报表吗？" onConfirm={() => deleteReport(month)} okButtonProps={{ loading: deleting }}><Button loading={deleting} size="small" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space>;
    } },
  ];

  const historyRecords = [...(data.sources.sales_history_rolling?.records || [])].sort((left, right) => String(right['月份'] || '').localeCompare(String(left['月份'] || '')));
  const historyColumns: TableProps<SourceRecord>['columns'] = [
    { title: '月份', dataIndex: '月份' },
    { title: '原始文件名', dataIndex: '原始文件名', ellipsis: true },
    { title: '上传时间', dataIndex: '上传时间' },
    { title: '大小', dataIndex: '文件大小', render: fileSize },
    { title: '操作', render: (_, row) => { const month = String(row['月份']); return <Button size="small" icon={<DownloadOutlined />} href={`/api/reports/sales-history/${encodeURIComponent(month)}/download`} onClick={event => { event.preventDefault(); void downloadWithFeedback(`/api/reports/sales-history/${encodeURIComponent(month)}/download`, `${month}.csv`, `${month}销量原始表`); }}>下载</Button>; } },
  ];

  const sourceCard = (definition: typeof sourceDefinitions[number]) => {
    const record = data.sources[definition.key]?.records?.[0];
    const uploading = isPending(`upload-${definition.key}`); const previewing = isPending(`preview-${definition.key}`); const deleting = isPending(`delete-${definition.key}`);
    return <Card key={definition.key} title={definition.title} data-testid={`source-${definition.key}`}>
      <Typography.Paragraph type="secondary">{definition.description}</Typography.Paragraph>
      {record ? <div className="source-record"><Tag color="success">已上传</Tag><Typography.Text>{String(record['原始文件名'] || '')}</Typography.Text><Typography.Text type="secondary">{String(record['上传时间'] || '')} · {fileSize(record['文件大小'])}</Typography.Text></div> : <Typography.Paragraph type="secondary">暂未上传</Typography.Paragraph>}
      <Spin spinning={uploading} tip="正在校验并保存…">
        <Dragger {...uploader(definition.key, `/api/reports/source/${definition.key}`, false, definition.accept)} disabled={uploading || deleting} className="source-dragger">
          <p className="ant-upload-drag-icon"><InboxOutlined /></p><p className="ant-upload-text">拖拽文件到这里，或点击选择</p><p className="ant-upload-hint">支持 {definition.accept}；上传后自动校验并替换当前文件</p>
        </Dragger>
      </Spin>
      {record && <Space wrap className="source-actions"><Button loading={previewing} disabled={deleting} icon={<EyeOutlined />} onClick={() => void showPreview(definition.key)}>预览</Button><Button disabled={deleting} icon={<DownloadOutlined />} href={`/api/reports/source/${definition.key}/download`} onClick={event => { event.preventDefault(); void downloadWithFeedback(`/api/reports/source/${definition.key}/download`, `${definition.key}.csv`, definition.title); }}>下载</Button><Popconfirm title={`确定删除${definition.title}吗？`} onConfirm={() => deleteSource(definition.key)} okButtonProps={{ loading: deleting }}><Button loading={deleting} danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space>}
    </Card>;
  };


  return <div className="upload-center-page">
    <div className="page-heading"><div><Typography.Title level={2}>上传中心</Typography.Title><Typography.Text type="secondary">所有文件会先执行字段与格式校验，通过后才会覆盖现有数据。{lastUpdated && ` · 数据更新时间 ${lastUpdated}`}</Typography.Text></div><Button loading={initialLoading} disabled={Object.keys(pending).length > 0} icon={<ReloadOutlined />} onClick={() => void manualRefresh()}>刷新记录</Button></div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="上传中心操作失败" description={error} action={<Button size="small" onClick={() => void manualRefresh()}>重新加载</Button>} />}
    <Spin spinning={initialLoading} tip="正在读取上传记录…"><div className="page-loading-min-height">
      {tab === 'daily' && <div className="upload-grid">{sourceDefinitions.filter(definition => definition.frequency === 'daily').map(sourceCard)}</div>}
      {tab === 'weekly' && <>
        <div className="upload-grid">
          <Card title="业绩报表 CSV" data-testid="performance-reports"><Typography.Paragraph type="secondary">支持一次拖入或选择多个文件；相同月份会替换原记录。</Typography.Paragraph><Spin spinning={isPending('upload-performance')} tip="正在逐个校验并保存…"><Dragger {...uploader('performance', '/api/reports/performance', true, '.csv')} disabled={isPending('upload-performance')} className="source-dragger"><p className="ant-upload-drag-icon"><InboxOutlined /></p><p className="ant-upload-text">拖拽一个或多个 CSV 到这里，或点击选择</p><p className="ant-upload-hint">每个文件都会先校验，再保存为对应月份的业绩报表</p></Dragger></Spin></Card>
          {sourceDefinitions.filter(definition => definition.frequency === 'weekly').map(sourceCard)}
        </div>
        <Card title="已上传业绩报表" className="section-card"><Table rowKey={row => String(row['月份'])} columns={reportColumns} dataSource={data.reports} pagination={{ pageSize: 8 }} scroll={{ x: 760 }} locale={{ emptyText: '暂无业绩报表' }} /></Card>
      </>}
      {tab === 'monthly' && <>
        <div className="upload-grid">{sourceDefinitions.filter(definition => definition.frequency === 'monthly').map(sourceCard)}</div>
        <Card title="往月销量原始表" data-testid="sales-history-rolling" className="section-card">
        <Typography.Paragraph type="secondary">支持一次上传多个完整自然月 CSV；首次需提供连续 12 个月，后续上传新月份会自动滚动替换最早月份，同月份重新上传会覆盖原记录。</Typography.Paragraph>
        <Spin spinning={isPending('upload-sales-history')} tip="正在逐个校验并保存…">
          <Dragger {...uploader('sales-history', '/api/reports/sales-history', true, '.csv')} disabled={isPending('upload-sales-history') || isPending('delete-sales-history')} className="source-dragger">
            <p className="ant-upload-drag-icon"><InboxOutlined /></p><p className="ant-upload-text">拖拽一个或多个月度 CSV 到这里，或点击选择</p><p className="ant-upload-hint">仅接受已结束的完整自然月；系统始终保留连续 12 个月</p>
          </Dragger>
        </Spin>
        <Space wrap className="source-actions"><Tag color={historyRecords.length === 12 ? 'success' : 'warning'}>{historyRecords.length}/12 个月</Tag><Popconfirm title="确定清空全部往月销量原始表吗？" description="清空后补货页将暂时没有销量画像。" onConfirm={() => void deleteSalesHistory()} okButtonProps={{ loading: isPending('delete-sales-history') }}><Button danger loading={isPending('delete-sales-history')} icon={<DeleteOutlined />}>清空全部</Button></Popconfirm></Space>
        <Table rowKey={row => String(row['月份'])} columns={historyColumns} dataSource={historyRecords} pagination={{ pageSize: 12, hideOnSinglePage: true }} scroll={{ x: 760 }} locale={{ emptyText: '暂无往月销量原始表' }} />
        </Card>
      </>}
    </div></Spin>
    <Modal width="90vw" title={preview ? `${preview.title}预览（共 ${preview.total} 行，显示前 ${preview.rows.length} 行）` : '数据预览'} open={!!preview} footer={null} onCancel={() => setPreview(undefined)} destroyOnHidden>{preview && <Table rowKey={(_, index) => String(index)} size="small" columns={preview.columns.map(column => ({ title: column, dataIndex: column, key: column, ellipsis: true }))} dataSource={preview.rows} scroll={{ x: 'max-content', y: 500 }} pagination={{ pageSize: 15 }} />}</Modal>
  </div>;
}
