import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Modal, Popconfirm, Space, Spin, Table, Tag, Typography, Upload, message } from 'antd';
import { DeleteOutlined, DownloadOutlined, EyeOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import type { TableProps, UploadProps } from 'antd';
import { api, apiErrorMessage, type ReportsResponse, type SourceRecord } from './api';

const sourceDefinitions = [
  { key: 'operational_sales', title: '运营原始表', accept: '.xls,.xlsx', description: '个人销量、库存、库龄、产品和补货分析的核心数据源' },
  { key: 'gross_profit', title: '毛利原始表', accept: '.csv,.xls,.xlsx', description: '产品毛利率、广告费和异常原因分析' },
  { key: 'rating', title: 'Rating', accept: '.xls,.xlsx', description: 'ASIN 各站点评分和评价数量' },
  { key: 'sales_volume_detail', title: '销量明细', accept: '.csv', description: '部门监控的销量明细数据' },
  { key: 'sales_amount_detail', title: '销售额明细', accept: '.csv', description: '部门监控的销售额明细数据' },
];
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

export default function UploadCenter() {
  const [data, setData] = useState<ReportsResponse>({ reports: [], sources: {} });
  const [initialLoading, setInitialLoading] = useState(true);
  const [pending, setPending] = useState<Record<string, number>>({});
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');
  const [preview, setPreview] = useState<{ title: string; columns: string[]; rows: Record<string, unknown>[]; total: number }>();

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
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取上传记录失败');
    } finally {
      if (showLoading) setInitialLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

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
          message.warning({ content: `${displayName} 上传成功；${warnings.join('；')}`, key: noticeKey, duration: 6 });
        } else {
          message.success({ content: `${displayName} 上传成功，已整批校验并保存`, key: noticeKey, duration: 2.5 });
        }
        await refresh(false, false);
      } catch (uploadError) {
        const detail = uploadError instanceof Error ? `${displayName} 上传失败：${uploadError.message}` : `${displayName} 上传失败`;
        setError(detail);
        message.error({ content: detail, key: noticeKey, duration: 3 });
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
    catch (previewError) { setError(previewError instanceof Error ? previewError.message : '预览失败'); }
    finally { end(operationKey); }
  };
  const deleteSource = async (key: string) => {
    const operationKey = `delete-${key}`;
    begin(operationKey); setError('');
    try { await api.deleteSource(key); message.success('已删除'); await refresh(false, false); }
    catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : '删除失败'); }
    finally { end(operationKey); }
  };
  const deleteReport = async (month: string) => {
    const operationKey = `delete-report-${month}`;
    begin(operationKey); setError('');
    try { await api.deleteReport(month); message.success('已删除'); await refresh(false, false); }
    catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : '删除失败'); }
    finally { end(operationKey); }
  };

  const reportColumns: TableProps<SourceRecord>['columns'] = [
    { title: '月份', dataIndex: '月份' }, { title: '原始文件名', dataIndex: '原始文件名', ellipsis: true },
    { title: '上传时间', dataIndex: '上传时间' }, { title: '大小', dataIndex: '文件大小', render: fileSize },
    { title: '操作', render: (_, row) => {
      const month = String(row['月份']); const deleting = isPending(`delete-report-${month}`);
      return <Space><Button disabled={deleting} size="small" icon={<DownloadOutlined />} href={`/api/reports/performance/${encodeURIComponent(month)}/download`}>下载</Button><Popconfirm title="确定删除该月份报表吗？" onConfirm={() => deleteReport(month)} okButtonProps={{ loading: deleting }}><Button loading={deleting} size="small" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space>;
    } },
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
      {record && <Space wrap className="source-actions"><Button loading={previewing} disabled={deleting} icon={<EyeOutlined />} onClick={() => void showPreview(definition.key)}>预览</Button><Button disabled={deleting} icon={<DownloadOutlined />} href={`/api/reports/source/${definition.key}/download`}>下载</Button><Popconfirm title={`确定删除${definition.title}吗？`} onConfirm={() => deleteSource(definition.key)} okButtonProps={{ loading: deleting }}><Button loading={deleting} danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space>}
    </Card>;
  };

  return <>
    <div className="page-heading"><div><Typography.Title level={2}>上传中心</Typography.Title><Typography.Text type="secondary">所有文件会先执行字段与格式校验，通过后才会覆盖现有数据。{lastUpdated && ` · 数据更新时间 ${lastUpdated}`}</Typography.Text></div><Button loading={initialLoading} disabled={Object.keys(pending).length > 0} icon={<ReloadOutlined />} onClick={() => void refresh()}>刷新记录</Button></div>
    {error && <Alert className="persistent-page-error" type="error" showIcon message="上传中心操作失败" description={error} action={<Button size="small" onClick={() => void refresh()}>重新加载</Button>} />}
    <Spin spinning={initialLoading} tip="正在读取上传记录…"><div className="page-loading-min-height">
      <Typography.Title level={4}>个人监控数据源</Typography.Title>
      <div className="upload-grid">
        {sourceDefinitions.slice(0, 3).map(sourceCard)}
        <Card title="业绩报表 CSV" data-testid="performance-reports"><Typography.Paragraph type="secondary">支持一次拖入或选择多个文件；相同月份会替换原记录。</Typography.Paragraph><Spin spinning={isPending('upload-performance')} tip="正在逐个校验并保存…"><Dragger {...uploader('performance', '/api/reports/performance', true, '.csv')} disabled={isPending('upload-performance')} className="source-dragger"><p className="ant-upload-drag-icon"><InboxOutlined /></p><p className="ant-upload-text">拖拽一个或多个 CSV 到这里，或点击选择</p><p className="ant-upload-hint">每个文件都会先校验，再保存为对应月份的业绩报表</p></Dragger></Spin></Card>
      </div>
      <Card title="已上传业绩报表" className="section-card"><Table rowKey={row => String(row['月份'])} columns={reportColumns} dataSource={data.reports} pagination={{ pageSize: 8 }} scroll={{ x: 760 }} locale={{ emptyText: '暂无业绩报表' }} /></Card>
      <Typography.Title level={4}>部门监控数据源</Typography.Title>
      <div className="upload-grid">{sourceDefinitions.slice(3).map(sourceCard)}</div>
    </div></Spin>
    <Modal width="90vw" title={preview ? `${preview.title}预览（共 ${preview.total} 行，显示前 ${preview.rows.length} 行）` : '数据预览'} open={!!preview} footer={null} onCancel={() => setPreview(undefined)} destroyOnHidden>{preview && <Table rowKey={(_, index) => String(index)} size="small" columns={preview.columns.map(column => ({ title: column, dataIndex: column, key: column, ellipsis: true }))} dataSource={preview.rows} scroll={{ x: 'max-content', y: 500 }} pagination={{ pageSize: 15 }} />}</Modal>
  </>;
}
