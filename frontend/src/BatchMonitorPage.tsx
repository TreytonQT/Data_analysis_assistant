import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Drawer,
  Empty,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DownOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import {
  api,
  type BatchCopyLists,
  type BatchMonitorDetails,
  type BatchMonitorMetrics,
  type BatchMonitorPayload,
  type BatchMonitorRow,
  type BatchMonitorSku,
  type BatchOrphanPage,
} from './api';

type BatchView = 'incomplete' | 'all' | 'completed';

const emptyMetrics: BatchMonitorMetrics = {
  incomplete_batches: 0,
  pending_artwork_batches: 0,
  pending_shipment_skus: 0,
  pending_arrival_skus: 0,
};

function integer(value: number) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value || 0);
}

function price(value: number | null) {
  return value == null ? '未维护' : value.toFixed(2);
}

function progressPercent(current: number, total: number) {
  return total ? Math.min(100, Math.round((current / total) * 100)) : 0;
}

function completeState(row: BatchMonitorRow): BatchMonitorRow {
  return {
    ...row,
    is_complete: Boolean(
      row.artwork_completed_date
      && row.shipped_count === row.sku_count
      && row.arrived_count === row.sku_count
    ),
  };
}

function rowVisible(row: BatchMonitorRow, view: BatchView) {
  return view === 'all'
    || (view === 'completed' && row.is_complete)
    || (view === 'incomplete' && !row.is_complete);
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <Card className={`batch-monitor-metric ${tone}`}>
    <Typography.Text>{label}</Typography.Text>
    <strong>{integer(value)}</strong>
  </Card>;
}

function BatchProgress({
  label,
  current,
  total,
  color,
}: {
  label: string;
  current: number;
  total: number;
  color: string;
}) {
  return <div className="batch-progress">
    <div><span>{label}</span><strong>{current}/{total}</strong></div>
    <Progress
      percent={progressPercent(current, total)}
      showInfo={false}
      strokeColor={color}
      trailColor="rgba(148, 163, 184, .24)"
      size="small"
    />
  </div>;
}

export default function BatchMonitorPage({
  active = true,
  routeVersion = 0,
  refreshVersion = 0,
}: {
  active?: boolean;
  routeVersion?: number;
  refreshVersion?: number;
}) {
  const [payload, setPayload] = useState<BatchMonitorPayload>();
  const [view, setView] = useState<BatchView>('incomplete');
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [initialLoading, setInitialLoading] = useState(true);
  const [softLoading, setSoftLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [details, setDetails] = useState<Record<string, BatchMonitorDetails>>({});
  const [detailLoading, setDetailLoading] = useState<Set<string>>(new Set());
  const [actionKey, setActionKey] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [batchNo, setBatchNo] = useState('');
  const [batchFile, setBatchFile] = useState<File>();
  const [creating, setCreating] = useState(false);
  const shipmentInput = useRef<HTMLInputElement>(null);
  const [orphanOpen, setOrphanOpen] = useState(false);
  const [orphans, setOrphans] = useState<BatchOrphanPage>();
  const [orphanSearch, setOrphanSearch] = useState('');
  const [orphanLoading, setOrphanLoading] = useState(false);
  const [copyLists, setCopyLists] = useState<BatchCopyLists>();
  const [copyListsLoading, setCopyListsLoading] = useState(false);
  const [arrivalTarget, setArrivalTarget] = useState<{ batchNo: string; sku: BatchMonitorSku }>();
  const [arrivalDate, setArrivalDate] = useState<Dayjs | null>(dayjs());
  const [arrivalSaving, setArrivalSaving] = useState(false);
  const [shipmentArrivalOpen, setShipmentArrivalOpen] = useState(false);
  const [shipmentArrivalNo, setShipmentArrivalNo] = useState('');
  const [shipmentArrivalDate, setShipmentArrivalDate] = useState<Dayjs | null>(dayjs());
  const [shipmentArrivalSaving, setShipmentArrivalSaving] = useState(false);
  const loaded = useRef(false);
  const requestId = useRef(0);
  const copyListsRequestId = useRef(0);

  const load = useCallback(async (
    nextView: BatchView,
    nextSearch: string,
    nextPage: number,
    showInitial = false,
  ) => {
    const currentRequest = ++requestId.current;
    if (showInitial) setInitialLoading(true); else setSoftLoading(true);
    setError('');
    try {
      const result = await api.batchMonitor({
        view: nextView,
        search: nextSearch,
        page: nextPage,
        page_size: 20,
      });
      if (currentRequest !== requestId.current) return;
      setPayload(result);
      setPage(result.page);
      loaded.current = true;
    } catch (loadError) {
      if (currentRequest !== requestId.current) return;
      setError(loadError instanceof Error ? loadError.message : '批次监控读取失败');
    } finally {
      if (currentRequest === requestId.current) {
        setInitialLoading(false);
        setSoftLoading(false);
      }
    }
  }, []);

  const loadCopyLists = useCallback(async () => {
    const currentRequest = ++copyListsRequestId.current;
    setCopyListsLoading(true);
    try {
      const result = await api.batchCopyLists();
      if (currentRequest === copyListsRequestId.current) setCopyLists(result);
    } catch (loadError) {
      if (currentRequest === copyListsRequestId.current) {
        setError(loadError instanceof Error ? loadError.message : '可复制清单读取失败');
      }
    } finally {
      if (currentRequest === copyListsRequestId.current) setCopyListsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void load(view, search, page, !loaded.current);
    void loadCopyLists();
    // View/search/page changes are submitted explicitly by the handlers below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, routeVersion, refreshVersion, load, loadCopyLists]);

  const changeView = (value: string | number) => {
    const next = String(value) as BatchView;
    setView(next);
    setPage(1);
    void load(next, search, 1);
  };

  const submitSearch = (value = searchDraft) => {
    const next = value.trim();
    setSearch(next);
    setPage(1);
    void load(view, next, 1);
  };

  const changePage = (next: number) => {
    setPage(next);
    void load(view, search, next);
  };

  const loadDetails = useCallback(async (batch: string, force = false) => {
    if (!force && details[batch]) return;
    setDetailLoading(current => new Set(current).add(batch));
    setError('');
    try {
      const result = await api.batchDetails(batch);
      setDetails(current => ({ ...current, [batch]: result }));
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : '批次SKU明细读取失败');
    } finally {
      setDetailLoading(current => {
        const next = new Set(current);
        next.delete(batch);
        return next;
      });
    }
  }, [details]);

  const toggleBatch = (batch: string) => {
    const opening = !expanded.has(batch);
    setExpanded(current => {
      const next = new Set(current);
      if (next.has(batch)) next.delete(batch); else next.add(batch);
      return next;
    });
    if (opening) void loadDetails(batch);
  };

  const patchBatch = (
    batch: string,
    mutate: (row: BatchMonitorRow) => BatchMonitorRow,
    mutateMetrics: (metrics: BatchMonitorMetrics, oldRow: BatchMonitorRow, newRow: BatchMonitorRow) => BatchMonitorMetrics,
  ) => {
    setPayload(current => {
      if (!current) return current;
      const oldRow = current.rows.find(row => row.batch_no === batch);
      if (!oldRow) return current;
      const newRow = completeState(mutate(oldRow));
      const visible = rowVisible(newRow, current.view);
      const nextRows = visible
        ? current.rows.map(row => row.batch_no === batch ? newRow : row)
        : current.rows.filter(row => row.batch_no !== batch);
      return {
        ...current,
        rows: nextRows,
        total: Math.max(0, current.total + (visible ? 0 : -1)),
        metrics: mutateMetrics(current.metrics, oldRow, newRow),
      };
    });
  };

  const updateArtwork = async (row: BatchMonitorRow, completed: boolean) => {
    const key = `artwork-${row.batch_no}`;
    setActionKey(key);
    setError('');
    try {
      const result = await api.updateBatchArtwork(row.batch_no, completed);
      patchBatch(
        row.batch_no,
        current => ({ ...current, artwork_completed_date: result.artwork_completed_date }),
        (metrics, oldRow, newRow) => ({
          ...metrics,
          pending_artwork_batches: Math.max(
            0,
            metrics.pending_artwork_batches
              + (oldRow.artwork_completed_date ? 0 : -1)
              + (newRow.artwork_completed_date ? 0 : 1),
          ),
          incomplete_batches: Math.max(
            0,
            metrics.incomplete_batches
              + (newRow.is_complete ? 0 : 1)
              - (oldRow.is_complete ? 0 : 1),
          ),
        }),
      );
      setDetails(current => current[row.batch_no]
        ? {
          ...current,
          [row.batch_no]: {
            ...current[row.batch_no],
            batch: completeState({
              ...current[row.batch_no].batch,
              artwork_completed_date: result.artwork_completed_date,
            }),
          },
        }
        : current);
      message.success(completed ? `${row.batch_no}美工图已完成` : `${row.batch_no}已撤销美工图完成`);
    } catch (artworkError) {
      setError(artworkError instanceof Error ? artworkError.message : '美工图状态保存失败');
    } finally {
      setActionKey('');
    }
  };

  const patchArrivalCount = (batch: string, delta: number) => {
    if (!delta) return;
    patchBatch(
      batch,
      current => ({
        ...current,
        arrived_count: Math.max(0, Math.min(current.sku_count, current.arrived_count + delta)),
      }),
      (metrics, oldRow, newRow) => ({
        ...metrics,
        pending_arrival_skus: Math.max(0, metrics.pending_arrival_skus - delta),
        incomplete_batches: Math.max(
          0,
          metrics.incomplete_batches
            + (newRow.is_complete ? 0 : 1)
            - (oldRow.is_complete ? 0 : 1),
        ),
      }),
    );
  };

  const openShipmentArrival = (shipmentNo = '') => {
    setShipmentArrivalNo(shipmentNo.toUpperCase());
    setShipmentArrivalDate(dayjs());
    setShipmentArrivalOpen(true);
  };

  const saveShipmentArrival = async () => {
    const shipmentNo = shipmentArrivalNo.trim().toUpperCase();
    if (!shipmentNo || !shipmentArrivalDate) {
      message.warning('请填写货件单号和到货日期');
      return;
    }
    setShipmentArrivalSaving(true);
    setError('');
    try {
      const result = await api.updateShipmentArrival(
        shipmentNo,
        shipmentArrivalDate.format('YYYY-MM-DD'),
      );
      setDetails(current => Object.fromEntries(
        Object.entries(current).map(([batchNo, detail]) => [
          batchNo,
          {
            ...detail,
            skus: detail.skus.map(sku => (
              sku.shipment_no === shipmentNo && !sku.arrival_date
                ? { ...sku, arrival_date: result.arrival_date }
                : sku
            )),
          },
        ]),
      ));
      setPayload(current => {
        if (!current) return current;
        const affected = new Map(
          result.affected_batches.map(item => [item.batch_no, item]),
        );
        const completedNow = result.affected_batches.filter(item => item.is_complete).length;
        const monitoredUpdated = result.affected_batches.reduce(
          (sum, item) => sum + item.updated_skus,
          0,
        );
        const rows = current.rows
          .map(row => {
            const update = affected.get(row.batch_no);
            return update
              ? { ...row, arrived_count: update.arrived_count, is_complete: update.is_complete }
              : row;
          })
          .filter(row => rowVisible(row, current.view));
        const totalDelta = current.view === 'incomplete'
          ? -completedNow
          : current.view === 'completed'
            ? completedNow
            : 0;
        return {
          ...current,
          rows,
          total: Math.max(0, current.total + totalDelta),
          metrics: {
            ...current.metrics,
            pending_arrival_skus: Math.max(
              0,
              current.metrics.pending_arrival_skus - monitoredUpdated,
            ),
            incomplete_batches: Math.max(
              0,
              current.metrics.incomplete_batches - completedNow,
            ),
          },
        };
      });
      setShipmentArrivalOpen(false);
      setShipmentArrivalNo('');
      setShipmentArrivalDate(dayjs());
      message.success(`${shipmentNo}新增${result.updated}个已到货SKU`);
      void load(view, search, page);
      void loadCopyLists();
    } catch (arrivalError) {
      setError(arrivalError instanceof Error ? arrivalError.message : '货件到货状态保存失败');
    } finally {
      setShipmentArrivalSaving(false);
    }
  };

  const openSkuArrival = (batch: string, sku: BatchMonitorSku) => {
    setArrivalTarget({ batchNo: batch, sku });
    setArrivalDate(dayjs(sku.arrival_date || undefined));
  };

  const saveSkuArrival = async () => {
    if (!arrivalTarget || !arrivalDate) return;
    setArrivalSaving(true);
    setError('');
    try {
      const result = await api.updateSkuArrival(
        arrivalTarget.sku.sku,
        true,
        arrivalDate.format('YYYY-MM-DD'),
      );
      const wasPending = !arrivalTarget.sku.arrival_date;
      setDetails(current => ({
        ...current,
        [arrivalTarget.batchNo]: {
          ...current[arrivalTarget.batchNo],
          skus: current[arrivalTarget.batchNo].skus.map(sku => (
            sku.sku === arrivalTarget.sku.sku
              ? { ...sku, arrival_date: result.arrival_date }
              : sku
          )),
        },
      }));
      if (wasPending) patchArrivalCount(arrivalTarget.batchNo, 1);
      setArrivalTarget(undefined);
      message.success(`${arrivalTarget.sku.sku}到货日期已保存`);
      void loadCopyLists();
    } catch (arrivalError) {
      setError(arrivalError instanceof Error ? arrivalError.message : 'SKU到货日期保存失败');
    } finally {
      setArrivalSaving(false);
    }
  };

  const clearSkuArrival = async (batch: string, sku: BatchMonitorSku) => {
    const key = `sku-clear-${sku.sku}`;
    setActionKey(key);
    setError('');
    try {
      await api.updateSkuArrival(sku.sku, false);
      setDetails(current => ({
        ...current,
        [batch]: {
          ...current[batch],
          skus: current[batch].skus.map(item => (
            item.sku === sku.sku ? { ...item, arrival_date: null } : item
          )),
        },
      }));
      if (sku.arrival_date) patchArrivalCount(batch, -1);
      message.success(`${sku.sku}已撤销到货`);
      void loadCopyLists();
    } catch (arrivalError) {
      setError(arrivalError instanceof Error ? arrivalError.message : 'SKU到货状态撤销失败');
    } finally {
      setActionKey('');
    }
  };

  const createBatch = async () => {
    if (!batchNo.trim() || !batchFile) {
      message.warning('请填写批次号并选择Excel文件');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const result = await api.createBatch(batchNo.trim(), batchFile);
      message.success(
        `${result.batch_no}已创建：源文件${result.source_sku_count}个SKU，`
        + `导入${result.imported_sku_count}个，忽略${result.ignored_sku_count}个`,
        7,
      );
      setCreateOpen(false);
      setBatchNo('');
      setBatchFile(undefined);
      setPage(1);
      await Promise.all([load(view, search, 1), loadCopyLists()]);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '新建批次失败');
    } finally {
      setCreating(false);
    }
  };

  const uploadShipments = async (file?: File) => {
    if (!file) return;
    setActionKey('upload-shipments');
    setError('');
    try {
      const result = await api.uploadBatchShipments(file);
      const preserved = result.conflicts ? `，${result.conflicts}个SKU保留了历史首次货件` : '';
      message.success(
        `货件上传完成：新增${result.inserted}，忽略${result.ignored}，未归属${result.unassigned}${preserved}`,
        6,
      );
      setDetails({});
      await Promise.all([load(view, search, page), loadCopyLists()]);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '货件列表上传失败');
    } finally {
      setActionKey('');
      if (shipmentInput.current) shipmentInput.current.value = '';
    }
  };

  const loadOrphans = async (nextSearch = orphanSearch, nextPage = 1) => {
    setOrphanLoading(true);
    setError('');
    try {
      setOrphans(await api.batchOrphans({
        search: nextSearch.trim(),
        page: nextPage,
        page_size: 50,
      }));
    } catch (orphanError) {
      setError(orphanError instanceof Error ? orphanError.message : '未归属SKU读取失败');
    } finally {
      setOrphanLoading(false);
    }
  };

  const openOrphans = () => {
    setOrphanOpen(true);
    void loadOrphans('', 1);
  };

  const copyLines = async (items: string[], label: string) => {
    if (!items.length) {
      message.info(`暂无${label}可复制`);
      return;
    }
    const text = items.join('\n');
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (!copied) throw new Error('copy failed');
      }
      message.success(`已复制${items.length}个${label}`);
    } catch {
      message.error('复制失败，请在清单中全选后复制');
    }
  };

  const renderDetails = (row: BatchMonitorRow) => {
    if (detailLoading.has(row.batch_no)) {
      return <div className="batch-detail-state"><Spin size="small" /> 正在加载SKU明细…</div>;
    }
    const detail = details[row.batch_no];
    if (!detail) {
      return <div className="batch-detail-state"><Button onClick={() => void loadDetails(row.batch_no, true)}>重试加载</Button></div>;
    }
    const pendingShipments = Array.from(new Set(
      detail.skus
        .filter(sku => sku.shipment_no && !sku.arrival_date)
        .map(sku => sku.shipment_no as string),
    ));
    return <div className="batch-detail-panel">
      {pendingShipments.length > 0 && <div className="batch-pending-shipments">
        <span>待到货货件</span>
        {pendingShipments.map(shipment => <Button
          key={shipment}
          size="small"
          onClick={() => openShipmentArrival(shipment)}
        >
          {shipment} · 整票到货
        </Button>)}
      </div>}
      <div className="batch-sku-grid batch-sku-grid-header" role="row">
        <span>SKU</span><span>四站开售价</span><span>ASIN</span><span>首次货件</span><span>到货</span>
      </div>
      <div className="batch-sku-grid-body">
        {detail.skus.map(sku => <div className="batch-sku-grid" role="row" key={sku.sku}>
          <strong data-label="SKU">{sku.sku}</strong>
          <span className="batch-price-grid" data-label="四站开售价">
            <i>DE {price(sku.de_price)}</i><i>FR {price(sku.fr_price)}</i>
            <i>ES {price(sku.es_price)}</i><i>IT {price(sku.it_price)}</i>
          </span>
          <span data-label="ASIN">{sku.asin || '—'}</span>
          <span data-label="首次货件">{sku.shipment_no || <Tag>未发货</Tag>}</span>
          <span className="batch-arrival-actions" data-label="到货">
            {sku.arrival_date
              ? <>
                <Tag color="success">{sku.arrival_date}</Tag>
                <Button size="small" onClick={() => openSkuArrival(row.batch_no, sku)}>修改</Button>
                <Popconfirm
                  title={`撤销${sku.sku}的到货状态？`}
                  onConfirm={() => void clearSkuArrival(row.batch_no, sku)}
                >
                  <Button size="small" danger loading={actionKey === `sku-clear-${sku.sku}`}>撤销</Button>
                </Popconfirm>
              </>
              : sku.shipment_no
                ? <Button size="small" type="primary" onClick={() => openSkuArrival(row.batch_no, sku)}>标记到货</Button>
                : <span>—</span>}
          </span>
        </div>)}
      </div>
    </div>;
  };

  if (initialLoading) {
    return <div className="route-loading"><Spin size="large" tip="正在读取批次监控…" /></div>;
  }

  const metrics = payload?.metrics || emptyMetrics;
  return <div className="batch-monitor-page">
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>批次监控</Typography.Title>
        <Typography.Text type="secondary">首次货件永久绑定；批次级监控美工图、发货和到货进度。</Typography.Text>
      </div>
      <Space wrap>
        <Button
          icon={<InboxOutlined />}
          disabled={payload ? !payload.orphan_scope_available : false}
          title={payload?.orphan_scope_message || undefined}
          onClick={openOrphans}
        >
          未归属SKU {payload?.orphan_count || 0}
        </Button>
        <input
          ref={shipmentInput}
          hidden
          type="file"
          accept=".csv"
          onChange={event => void uploadShipments(event.target.files?.[0])}
        />
        <Button
          icon={<CloudUploadOutlined />}
          loading={actionKey === 'upload-shipments'}
          onClick={() => shipmentInput.current?.click()}
        >
          上传货件列表
        </Button>
        <Button icon={<CheckCircleOutlined />} onClick={() => openShipmentArrival()}>
          货件到货
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建批次</Button>
        <Button
          icon={<ReloadOutlined />}
          loading={softLoading || copyListsLoading}
          onClick={() => void Promise.all([
            load(view, search, page),
            loadCopyLists(),
          ])}
        >
          刷新
        </Button>
      </Space>
    </div>

    {error && <Alert
      className="persistent-page-error"
      type="error"
      showIcon
      message="批次监控操作失败"
      description={error}
      closable
      onClose={() => setError('')}
    />}

    <div className="batch-monitor-metrics">
      <MetricCard label="未完成批次" value={metrics.incomplete_batches} tone="metric-blue" />
      <MetricCard label="待美工批次" value={metrics.pending_artwork_batches} tone="metric-violet" />
      <MetricCard label="待发货SKU" value={metrics.pending_shipment_skus} tone="metric-orange" />
      <MetricCard label="待到货SKU" value={metrics.pending_arrival_skus} tone="metric-green" />
    </div>

    <div className="batch-copy-lists">
      <Card
        className="batch-copy-card"
        title={`未绑定货件单号的SKU（${copyLists?.unbound_shipment_count ?? 0}）`}
        extra={<Button
          size="small"
          icon={<CopyOutlined />}
          aria-label="复制全部未绑定货件单号的SKU"
          disabled={!copyLists?.unbound_shipment_skus.length}
          onClick={() => void copyLines(copyLists?.unbound_shipment_skus || [], '未绑定货件SKU')}
        >
          复制全部
        </Button>}
      >
        <Typography.Text type="secondary">仅显示已属于监控批次、但尚未绑定首次货件单号的SKU</Typography.Text>
        <Spin spinning={copyListsLoading}>
          <Input.TextArea
            className="batch-copy-textarea"
            aria-label="未绑定货件单号的SKU清单"
            readOnly
            rows={8}
            value={(copyLists?.unbound_shipment_skus || []).join('\n')}
            placeholder="暂无未绑定货件单号的SKU"
          />
        </Spin>
      </Card>
      <Card
        className="batch-copy-card"
        title={`未到货的货件单号（${copyLists?.pending_shipment_count ?? 0}）`}
        extra={<Button
          size="small"
          icon={<CopyOutlined />}
          aria-label="复制全部未到货的货件单号"
          disabled={!copyLists?.pending_shipment_nos.length}
          onClick={() => void copyLines(copyLists?.pending_shipment_nos || [], '未到货货件单号')}
        >
          复制全部
        </Button>}
      >
        <Typography.Text type="secondary">仅显示已绑定批次且仍有SKU未到货的货件，货件号自动去重</Typography.Text>
        <Spin spinning={copyListsLoading}>
          <Input.TextArea
            className="batch-copy-textarea"
            aria-label="未到货货件单号清单"
            readOnly
            rows={8}
            value={(copyLists?.pending_shipment_nos || []).join('\n')}
            placeholder="暂无未到货货件单号"
          />
        </Spin>
      </Card>
    </div>

    <Card className="batch-monitor-board" title="批次进度矩阵" extra={softLoading && <Spin size="small" />}>
      <div className="batch-monitor-toolbar">
        <Segmented
          value={view}
          onChange={changeView}
          options={[
            { label: '未完成', value: 'incomplete' },
            { label: '全部', value: 'all' },
            { label: '已完成', value: 'completed' },
          ]}
        />
        <Input.Search
          allowClear
          value={searchDraft}
          placeholder="搜索批次、SKU、ASIN、货件号"
          onChange={event => setSearchDraft(event.target.value)}
          onSearch={submitSearch}
          className="batch-monitor-search"
        />
      </div>

      {!payload?.rows.length
        ? <Empty description="当前条件下没有批次" />
        : <div className="batch-monitor-list">
          {payload.rows.map(row => {
            const isExpanded = expanded.has(row.batch_no);
            return <section className="batch-monitor-row" key={row.batch_no}>
              <div className="batch-monitor-row-main">
                <Button
                  type="text"
                  className="batch-expand-button"
                  aria-label={`${isExpanded ? '收起' : '展开'}${row.batch_no}`}
                  icon={isExpanded ? <DownOutlined /> : <RightOutlined />}
                  onClick={() => toggleBatch(row.batch_no)}
                />
                <div className="batch-identity">
                  <div>
                    <strong>{row.batch_no}</strong>
                    {row.is_complete ? <Tag color="success">全部完成</Tag> : <Tag color="processing">进行中</Tag>}
                  </div>
                  <span>{row.sku_count}个SKU · {row.shipment_count}个首次货件</span>
                </div>
                <div className="batch-artwork">
                  <span>美工图</span>
                  {row.artwork_completed_date
                    ? <>
                      <Tag color="success" icon={<CheckCircleOutlined />}>{row.artwork_completed_date}</Tag>
                      <Popconfirm
                        title={`撤销${row.batch_no}的美工图完成状态？`}
                        onConfirm={() => void updateArtwork(row, false)}
                      >
                        <Button size="small" danger loading={actionKey === `artwork-${row.batch_no}`}>撤销</Button>
                      </Popconfirm>
                    </>
                    : <Button
                      size="small"
                      type="primary"
                      loading={actionKey === `artwork-${row.batch_no}`}
                      onClick={() => void updateArtwork(row, true)}
                    >
                      完成美工图
                    </Button>}
                </div>
                <BatchProgress label="已发货" current={row.shipped_count} total={row.sku_count} color="#f59e0b" />
                <BatchProgress label="已到货" current={row.arrived_count} total={row.sku_count} color="#22c55e" />
              </div>
              {isExpanded && renderDetails(row)}
            </section>;
          })}
        </div>}
      {(payload?.total || 0) > 20 && <Pagination
        current={page}
        pageSize={20}
        total={payload?.total || 0}
        showSizeChanger={false}
        onChange={changePage}
        className="batch-monitor-pagination"
      />}
    </Card>

    <Modal
      title="新建批次"
      open={createOpen}
      confirmLoading={creating}
      okText="创建批次"
      cancelText="取消"
      onOk={() => void createBatch()}
      onCancel={() => {
        if (creating) return;
        setCreateOpen(false);
        setBatchNo('');
        setBatchFile(undefined);
      }}
    >
      <div className="batch-create-form">
        <label>
          <span>批次号</span>
          <Input
            value={batchNo}
            maxLength={32}
            placeholder="例如 FAK260701"
            onChange={event => setBatchNo(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>批次Excel</span>
          <input
            type="file"
            accept=".xlsx"
            onChange={event => setBatchFile(event.target.files?.[0])}
          />
          <small>读取SKU及DE/FR/ES/IT_PRICE；重复批次或跨批次SKU会整批拒绝。</small>
        </label>
      </div>
    </Modal>

    <Modal
      title="货件到货"
      open={shipmentArrivalOpen}
      confirmLoading={shipmentArrivalSaving}
      okButtonProps={{ disabled: !shipmentArrivalNo.trim() || !shipmentArrivalDate }}
      okText="保存整票到货"
      cancelText="取消"
      onOk={() => void saveShipmentArrival()}
      onCancel={() => {
        if (shipmentArrivalSaving) return;
        setShipmentArrivalOpen(false);
        setShipmentArrivalNo('');
        setShipmentArrivalDate(dayjs());
      }}
    >
      <div className="batch-create-form">
        <label>
          <span>货件单号</span>
          <Input
            aria-label="货件单号"
            value={shipmentArrivalNo}
            maxLength={64}
            placeholder="例如 FBA15M1J9L5X"
            onChange={event => setShipmentArrivalNo(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>到货日期</span>
          <DatePicker
            aria-label="到货日期"
            value={shipmentArrivalDate}
            onChange={setShipmentArrivalDate}
            disabledDate={current => current.isAfter(dayjs(), 'day')}
            format="YYYY-MM-DD"
            allowClear={false}
            style={{ width: '100%' }}
          />
        </label>
      </div>
    </Modal>

    <Modal
      title={`${arrivalTarget?.sku.sku || ''} 到货日期`}
      open={Boolean(arrivalTarget)}
      confirmLoading={arrivalSaving}
      okButtonProps={{ disabled: !arrivalDate }}
      okText="保存到货"
      cancelText="取消"
      onOk={() => void saveSkuArrival()}
      onCancel={() => setArrivalTarget(undefined)}
    >
      <DatePicker
        value={arrivalDate}
        onChange={setArrivalDate}
        format="YYYY-MM-DD"
        allowClear={false}
        style={{ width: '100%' }}
      />
    </Modal>

    <Drawer
      title={`未归属批次的首次货件SKU（${orphans?.total ?? payload?.orphan_count ?? 0}）`}
      width="min(960px, 92vw)"
      open={orphanOpen}
      onClose={() => setOrphanOpen(false)}
    >
      <Input.Search
        allowClear
        placeholder="搜索SKU、ASIN、货件号"
        onSearch={value => {
          setOrphanSearch(value);
          void loadOrphans(value, 1);
        }}
      />
      <Spin spinning={orphanLoading}>
        <div className="batch-orphan-grid batch-orphan-header">
          <span>SKU</span><span>ASIN</span><span>首次货件</span><span>到货状态</span>
        </div>
        {orphans?.rows.map(row => <div className="batch-orphan-grid" key={row.sku}>
          <strong>{row.sku}</strong>
          <span>{row.asin}</span>
          <span>{row.shipment_no}</span>
          <span>{row.arrival_date || '未到货'}</span>
        </div>)}
        {(orphans?.total || 0) > 50 && <Pagination
          current={orphans?.page || 1}
          pageSize={50}
          total={orphans?.total || 0}
          showSizeChanger={false}
          onChange={next => void loadOrphans(orphanSearch, next)}
        />}
      </Spin>
    </Drawer>
  </div>;
}
