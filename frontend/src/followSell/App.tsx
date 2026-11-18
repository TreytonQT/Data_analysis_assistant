import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, App as AntApp, Button, Card, Input, Space, Switch, Table } from 'antd';
import { FileExcelOutlined, FolderOpenOutlined, UploadOutlined } from '@ant-design/icons';

import DesignSystemProvider from '../DesignSystemProvider';
import PageHeading from '../components/PageHeading';
import { PageLoading, SectionEmpty, SectionError } from '../components/PageState';
import { configureFeedback, feedbackMessage, isAbortError, runOperation } from '../feedback';
import { chooseDirectory, downloadResult, downloadTemplate, getSettings, processFiles, saveResult, shutdown, WorkbookError, type Issue, type Preview } from './api';
import oaTemplateReference from './assets/oa-update-template-reference.png';
import mabangListingReference from './assets/mabang-listing1-reference.svg';
import './followSell.css';

function FeedbackBridge() {
  const { message } = AntApp.useApp();
  useEffect(() => { configureFeedback(message); return () => configureFeedback(); }, [message]);
  return null;
}

function FilePicker({ number, title, file, onChange, disabled = false }: {
  number: number; title: string; file: File | null; onChange: (file: File | null) => void; disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return <div className="follow-file">
    <div className="follow-file-heading"><strong>【{number}】{title}</strong>
      <Button type="link" size="small" onClick={() => void downloadTemplate(number)}>下载模板</Button>
    </div>
    <div className="follow-file-control">
      <input ref={input} type="file" accept=".xlsx" aria-label={`上传${title}`} disabled={disabled}
        onChange={event => {
          const selected = event.target.files?.[0] || null;
          event.target.value = '';
          if (selected && !selected.name.toLowerCase().endsWith('.xlsx')) {
            feedbackMessage.error('请选择xlsx文件。');
            return;
          }
          onChange(selected);
        }} />
      <Button icon={<UploadOutlined />} onClick={() => input.current?.click()} disabled={disabled}>{file ? '替换文件' : '选择文件'}</Button>
      <span className={file ? 'follow-file-name' : 'follow-muted'} title={file?.name}>{file?.name || '尚未选择xlsx文件'}</span>
      {file && <Button type="text" size="small" disabled={disabled} onClick={() => onChange(null)}>移除</Button>}
    </div>
  </div>;
}

function IssueTable({ issues }: { issues: Issue[] }) {
  return <Table size="small" className="follow-issues" rowKey="id" scroll={{ x: 600 }}
    dataSource={issues.map((item, index) => ({ ...item, id: String(index) }))}
    pagination={issues.length > 5 ? { pageSize: 5, showSizeChanger: false } : false}
    columns={[
      { title: '文件 / Excel行', key: 'source', width: 150, render: (_, row) => `${row.file}${row.row ? ` · 第${row.row}行` : ''}` },
      { title: 'SKU', dataIndex: 'sku', width: 170, ellipsis: true },
      { title: '原因', dataIndex: 'message', width: 280 },
    ]} />;
}

export function Stage({ kind, mapping, outputDir, onBusy }: {
  kind: 'oa' | 'mabang'; mapping: File | null; outputDir: string; onBusy: (stage: string, busy: boolean) => void;
}) {
  const [first, setFirst] = useState<File | null>(null);
  const [second, setSecond] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState('');
  const [issues, setIssues] = useState<Issue[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState('');
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const isOa = kind === 'oa';
  const invalidate = useCallback(() => {
    revision.current += 1;
    controller.current?.abort();
    submitting.current = false;
    setPreview(null); setSaved(''); setError(''); setIssues([]); setBusy(false);
    onBusy(kind, false);
  }, [kind, onBusy]);
  useEffect(() => { invalidate(); }, [mapping, invalidate]);
  useEffect(() => () => { controller.current?.abort(); revision.current += 1; }, []);

  async function validate() {
    if (!mapping || !first || !second || submitting.current) return;
    invalidate();
    submitting.current = true;
    setBusy(true); onBusy(kind, true);
    const current = revision.current;
    controller.current = new AbortController();
    try {
      const result = await processFiles(kind, [mapping, first, second], controller.current.signal);
      if (current === revision.current) setPreview(result);
    } catch (reason) {
      if (current === revision.current && !isAbortError(reason)) {
        setError(reason instanceof Error ? reason.message : '校验失败，请重试。');
        setIssues(reason instanceof WorkbookError ? reason.issues : []);
      }
    } finally {
      if (current === revision.current) {
        submitting.current = false; setBusy(false); onBusy(kind, false);
      }
    }
  }
  async function save() {
    if (!preview || submitting.current) return;
    submitting.current = true; setBusy(true); onBusy(kind, true);
    const current = revision.current;
    try {
      const result = await runOperation(() => saveResult(preview.result_id, outputDir), {
        key: `save-${kind}`, loading: '正在保存结果…', success: '结果已保存',
      });
      if (current === revision.current) setSaved(result.path);
    } catch { /* Feedback retains the valid preview so saving can be retried. */ }
    finally {
      if (current === revision.current) { submitting.current = false; setBusy(false); onBusy(kind, false); }
    }
  }

  return <Card className="follow-stage" title={<h2>{isOa ? '生成OA更新表' : '生成替换马帮上架表1'}</h2>}
    extra={<span className="follow-muted">{isOa ? '步骤2–3' : '步骤4'}</span>}>
    <aside className="follow-replacement-note">
      <span>{isOa ? '替换艾巴达ERP产品批量更新模板' : '替换掉OA生成的马帮上架表1'}</span>
      <img src={isOa ? oaTemplateReference : mabangListingReference}
        alt={isOa ? '艾巴达ERP产品批量更新模板文件示例' : 'OA生成的马帮上架表1文件示例'} />
    </aside>
    <p className="follow-stage-description">{isOa ? '复制原OA信息，替换新SKU，并更新德、法、西、意售价。' : '读取原SKU马帮信息，保留新SKU标识和其余字段。'}</p>
    <FilePicker number={isOa ? 2 : 4} title={isOa ? '原店铺OA信息' : 'OA生成的马帮上架表1'} file={first} disabled={busy}
      onChange={file => { invalidate(); setFirst(file); }} />
    <FilePicker number={isOa ? 3 : 5} title={isOa ? '原店铺领星售价表' : '原店铺马帮信息表'} file={second} disabled={busy}
      onChange={file => { invalidate(); setSecond(file); }} />
    <div className="follow-stage-actions">
      <Button type={preview ? 'default' : 'primary'} loading={busy && !preview} disabled={!mapping || !first || !second || busy} onClick={() => void validate()}>校验并预览{isOa ? 'OA' : '马帮'}结果</Button>
      {preview && <Button type="primary" loading={busy} disabled={busy || !outputDir.trim() || Boolean(saved)} onClick={() => void save()}>保存结果{isOa ? '1' : '2'}</Button>}
      {!mapping && <span className="follow-muted">请先选择SKU映射表</span>}
    </div>
    {error && <div role="alert"><SectionError title="整批暂停" error={error} />{issues.length > 0 && <IssueTable issues={issues} />}</div>}
    {preview && <div className="follow-preview" aria-live="polite">
      <div className="follow-summary">
        <span>匹配 <strong>{preview.summary.matched_rows}</strong> 条</span>
        <span>输出 <strong>{preview.summary.output_rows}</strong> 条</span>
        <span>来源 <strong>{preview.summary.source_rows}</strong> 条</span>
        {isOa ? <span>售价回退 <strong>{preview.summary.fallback_prices}</strong> 处</span> : <span>更新 <strong>{preview.summary.updated_fields}</strong> 个字段</span>}
      </div>
      {preview.warnings.length > 0 && <>
        <Alert type="warning" showIcon message={`有${preview.warnings.length}处领星售价缺失，已沿用OA原售价，请核对。`} />
        <IssueTable issues={preview.warnings} />
      </>}
      <Table size="small" rowKey={preview.columns[0]} dataSource={preview.rows} scroll={{ x: isOa ? 1080 : 1220 }}
        pagination={{ pageSize: 5, showSizeChanger: false, showTotal: total => `共${total}条` }}
        columns={preview.columns.map(header => ({
          title: header, dataIndex: header, key: header, width: header.endsWith('_PRICE') ? 110 : 210,
          align: header.endsWith('_PRICE') || header === '商品重量' || header === '统一成本价' ? 'right' as const : 'left' as const,
          ellipsis: true, render: (value: unknown) => value == null || value === '' ? '—' : String(value),
        }))} />
      {saved && <Alert type="success" showIcon message="结果已保存" description={<div className="follow-saved-path">{saved}</div>}
        action={<Button size="small" onClick={() => void downloadResult(preview)}>下载副本</Button>} />}
    </div>}
  </Card>;
}

function Workspace() {
  const [mapping, setMapping] = useState<File | null>(null);
  const [outputDir, setOutputDir] = useState('');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [busyStages, setBusyStages] = useState<Record<string, boolean>>({});
  const [choosing, setChoosing] = useState(false);
  const [stopped, setStopped] = useState(false);
  const onBusy = useCallback((stage: string, busy: boolean) => setBusyStages(previous => ({ ...previous, [stage]: busy })), []);
  const busy = Object.values(busyStages).some(Boolean);
  const load = useCallback(async () => {
    setError('');
    try { const settings = await getSettings(); setOutputDir(settings.output_dir); setReady(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接本地程序。'); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function choose() {
    setChoosing(true);
    try {
      const result = await chooseDirectory();
      if (result.path) setOutputDir(result.path);
    } catch (reason) { feedbackMessage.error(reason instanceof Error ? reason.message : '无法打开目录选择，请直接填写路径。'); }
    finally { setChoosing(false); }
  }
  if (stopped) return <SectionEmpty description="程序已退出，可关闭此页面。再次使用时请双击EXE。" />;
  return <>
    <PageHeading title="亚马逊跟卖表格助手" description="从原SKU到新SKU，按字段生成OA与马帮导入表。"
      actions={<Button disabled={!ready || busy || choosing} onClick={async () => { try { await shutdown(); setStopped(true); } catch { feedbackMessage.error('退出失败，请重试。'); } }}>退出程序</Button>} />
    {error && <SectionError title="连接失败" error={error} onRetry={() => void load()} />}
    {!ready && !error && <PageLoading label="正在连接本地程序…" />}
    {ready && <>
      <Card className="follow-mapping">
        <div className="follow-mapping-inner">
          <FilePicker number={1} title="SKU映射表" file={mapping} onChange={setMapping} disabled={busy} />
          <div className="follow-mapping-note"><strong>两个阶段共用这份映射</strong><br />马帮阶段可单独使用【1】【4】【5】，无需再次处理OA。</div>
        </div>
      </Card>
      <div className="follow-stages">
        <Stage kind="oa" mapping={mapping} outputDir={outputDir} onBusy={onBusy} />
        <Stage kind="mabang" mapping={mapping} outputDir={outputDir} onBusy={onBusy} />
      </div>
      <Card className="follow-output">
        <label htmlFor="follow-output-dir">结果保存目录</label>
        <div className="follow-output-control">
          <Input id="follow-output-dir" value={outputDir} disabled={busy || choosing} onChange={event => setOutputDir(event.target.value)} />
          <Button icon={<FolderOpenOutlined />} loading={choosing} disabled={busy} onClick={() => void choose()}>选择目录</Button>
        </div>
      </Card>
      <p className="follow-footnote">仅在本机处理xlsx文件。填写模板前，请删除或替换红字示例；空白保持空白，原始文件不会被覆盖。</p>
    </>}
  </>;
}

export default function App() {
  const [dark, setDark] = useState(() => localStorage.getItem('follow-sell-theme') === 'dark');
  return <DesignSystemProvider dark={dark}><AntApp>
    <FeedbackBridge />
    <div className="follow-shell">
      <header className="follow-topbar"><span className="follow-brand"><FileExcelOutlined /> 跟卖表格助手</span>
        <Space><span className="follow-muted">深色模式</span><Switch aria-label="深色模式" checked={dark} onChange={value => { setDark(value); localStorage.setItem('follow-sell-theme', value ? 'dark' : 'light'); }} /></Space>
      </header>
      <main className="follow-main"><Workspace /></main>
    </div>
  </AntApp></DesignSystemProvider>;
}
