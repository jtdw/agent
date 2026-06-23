import { motion } from 'framer-motion';
import { BarChart3, Database, Download, FileArchive, Layers3, Map, PanelRightClose, RotateCcw, ScanSearch, Trash2, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { GlassCard } from './GlassCard';
import { LocalLibraryPanel } from './LocalLibraryPanel';
import { ResearchWorkflowPanel } from './ResearchWorkflowPanel';
import { SegmentedControl } from './SegmentedControl';
import { CommercialUser, DownloadJob, DownloadManagementView, WorkspaceDashboard, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { LayerVisibility } from './mapLayerPolicy';
import type { WorkflowAction } from './researchWorkflow';

type Basemap = 'standard' | 'satellite' | 'terrain' | 'dark';

type LayerItem = {
  id: string;
  name: string;
  desc: string;
  active: boolean;
  accent: string;
};

type DownloadProduct = {
  value: string;
  label: string;
  outputSuffix: string;
  requestLabel: string;
};

const downloadProducts: DownloadProduct[] = [
  { value: 'dem', label: 'DEM / 高程数据', outputSuffix: 'dem', requestLabel: 'DEM 数据' },
  { value: 'landsat8_oli_tirs', label: 'Landsat 8 OLI_TIRS', outputSuffix: 'landsat8', requestLabel: 'Landsat 8 OLI_TIRS 数据' },
  { value: 'modnd1t_ndvi_10day', label: 'MODND1T NDVI 旬合成', outputSuffix: 'modnd1t_ndvi', requestLabel: 'MODND1T 中国 500M NDVI 旬合成产品' },
  { value: 'modl1t_lst_composite', label: 'MODLT1T 地表温度旬合成', outputSuffix: 'modl1t_lst', requestLabel: 'MODLT1T 中国 1KM 地表温度旬合成产品' },
  { value: 'modev1t_evi_10day', label: 'MODEV1T 250M EVI 旬合成', outputSuffix: 'modev1t_evi', requestLabel: 'MODEV1T 中国 250M EVI 旬合成产品' },
  { value: 'mod021km_surface_reflectance', label: 'MOD021KM 1KM 地表反射率', outputSuffix: 'mod021km_reflectance', requestLabel: 'MOD021KM 1KM 地表反射率' },
  { value: 'sentinel2_msi', label: 'Sentinel-2 MSI', outputSuffix: 'sentinel2_msi', requestLabel: 'Sentinel-2 MSI 数据' }
];

function LayerThumb({ accent }: { accent: string }) {
  return (
    <div className="relative h-12 w-14 shrink-0 overflow-hidden rounded-2xl border border-white/55 bg-white/55 shadow-inner dark:border-white/10 dark:bg-white/5">
      <div className="absolute inset-0 opacity-70" style={{ background: `linear-gradient(135deg, ${accent}, transparent 62%)` }} />
      <svg viewBox="0 0 80 64" className="absolute inset-0 h-full w-full opacity-80">
        <path d="M0 46 C15 34 22 42 37 31 C54 20 62 28 80 16" fill="none" stroke="currentColor" strokeWidth="4" className="text-white/80" />
        <path d="M-5 60 C14 49 28 58 43 43 C56 31 66 39 86 25" fill="none" stroke="currentColor" strokeWidth="3" className="text-white/45" />
      </svg>
    </div>
  );
}

function GlowSwitch({ active, onClick }: { active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('relative h-7 w-12 shrink-0 overflow-hidden rounded-full border shadow-inner transition', active ? 'border-cyan-glow/50 bg-cyan-glow/30 shadow-glow' : 'border-slate-200 bg-slate-200/70 dark:border-white/10 dark:bg-white/10')}
      aria-pressed={active}
    >
      <span className={cn('absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-lg transition-transform duration-200 ease-out', active && 'translate-x-5')} />
    </button>
  );
}

const initialLayers: LayerItem[] = [
  { id: 'stations', name: '站点观测数据', desc: '土壤水分站点、样点表与时间序列', active: true, accent: '#0B5FF4' },
  { id: 'boundary', name: '研究区边界', desc: '流域边界、行政区裁剪范围与制图边界', active: true, accent: '#22D3EE' },
  { id: 'dem', name: 'DEM / 高程成果', desc: '地形、高程下载结果与待处理 DEM 图层', active: true, accent: '#38bdf8' },
  { id: 'soil', name: '土壤水分结果', desc: '融合建模结果、站点插值与专题图层', active: true, accent: '#10b981' },
  { id: 'uncertainty', name: '不确定性分析', desc: 'GCP 预测区间与空间可靠性', active: false, accent: '#f59e0b' },
  { id: 'download', name: '自动下载数据', desc: '地理空间数据云、DEM 与遥感产品', active: false, accent: '#8b5cf6' }
];

function hasLayerVisibility(id: string): id is keyof LayerVisibility {
  return id === 'stations' || id === 'boundary' || id === 'dem' || id === 'soil';
}

function attachManagementViews(jobs: DownloadJob[] = [], views: DownloadManagementView[] = []) {
  if (!jobs.length && views.length) {
    return views.map((view) => ({
      job_id: view.task_id,
      status: view.status,
      progress: view.progress,
      output_name: view.display_title,
      source_key: view.source_name,
      stage: view.action_state?.stage,
      updated_at: view.updated_at,
      management_view: view
    }));
  }
  if (!views.length) return jobs;
  const byId = new globalThis.Map(views.map((view) => [view.task_id, view]));
  return jobs.map((job) => ({ ...job, management_view: job.management_view || byId.get(job.job_id) }));
}

function jobView(job: DownloadJob) {
  return job.management_view;
}

function jobStatus(job: DownloadJob) {
  return jobView(job)?.status || 'running';
}

function jobProgress(job: DownloadJob) {
  return Number(jobView(job)?.progress ?? 0);
}

function jobTitle(job: DownloadJob) {
  return jobView(job)?.display_title || job.job_id;
}

function jobStage(job: DownloadJob) {
  return jobView(job)?.action_state?.stage || '--';
}

function jobActions(job: DownloadJob) {
  return jobView(job)?.available_actions || [];
}

function canJob(job: DownloadJob, action: string) {
  const actions = jobActions(job);
  if (actions.length) return actions.includes(action);
  if (action === 'cancel') return jobStatus(job) === 'running';
  if (action === 'view_artifacts') return Boolean(jobView(job)?.artifact_refs?.length);
  return false;
}

function jobState(job: DownloadJob, key: string) {
  return jobView(job)?.action_state?.[key] || '';
}

export function LayerPanel({
  user,
  sessionId,
  basemap,
  setBasemap,
  onClose,
  layerVisibility,
  onLayerToggle,
  onLayerLocate,
  onRunWorkflowAction
}: {
  user: CommercialUser | null;
  sessionId?: string;
  basemap: Basemap;
  setBasemap: (value: Basemap) => void;
  onClose?: () => void;
  layerVisibility: LayerVisibility;
  onLayerToggle: (id: keyof LayerVisibility) => void;
  onLayerLocate: (id: keyof LayerVisibility) => void;
  onRunWorkflowAction: (action: WorkflowAction) => void;
}) {
  const [side, setSide] = useState<'right' | 'left'>('right');
  const [busy, setBusy] = useState(false);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [downloadRegion, setDownloadRegion] = useState('成都市');
  const [downloadResourceType, setDownloadResourceType] = useState(downloadProducts[0].value);
  const [dashboard, setDashboard] = useState<WorkspaceDashboard | null>(null);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [layers, setLayers] = useState<LayerItem[]>(initialLayers);
  const completedSeenRef = useRef<Set<string>>(new Set());
  const jobsInitializedRef = useRef(false);
  const userId = user?.user_id || '';

  const refreshDashboard = () => {
    if (!user) {
      setDashboard(null);
      return;
    }
    api.dashboard(userId, sessionId).then(setDashboard).catch(() => setDashboard(null));
  };

  const refreshJobs = () => {
    if (!user) {
      setJobs([]);
      return;
    }
    api.jobs(userId, sessionId)
      .then((r) => {
        const nextJobs = attachManagementViews(r.jobs || [], r.management_views || []);
        setJobs(nextJobs);
        if (!jobsInitializedRef.current) {
          nextJobs
            .filter((job) => jobStatus(job) === 'succeeded')
            .forEach((job) => completedSeenRef.current.add(job.job_id));
          jobsInitializedRef.current = true;
          return;
        }
        const latestCompleted = nextJobs.find((job) => jobStatus(job) === 'succeeded' && !completedSeenRef.current.has(job.job_id));
        if (latestCompleted) {
          completedSeenRef.current.add(latestCompleted.job_id);
          setNotice(`下载任务已完成：${jobTitle(latestCompleted)}。可在“下载任务”中查看或下载结果。`);
          refreshDashboard();
        }
      })
      .catch(() => setJobs([]));
  };

  useEffect(() => {
    jobsInitializedRef.current = false;
    completedSeenRef.current.clear();
    refreshDashboard();
    refreshJobs();
    const timer = window.setInterval(() => {
      refreshDashboard();
      refreshJobs();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [sessionId, userId]);

  const submitPlatformJob = async () => {
    if (!user) {
      setNotice('请先登录账号，再提交下载任务。');
      return;
    }
    setBusy(true);
    try {
      const region = downloadRegion.trim() || '成都市';
      const product = downloadProducts.find((item) => item.value === downloadResourceType) || downloadProducts[0];
      const result = await api.submitDownload({
        user_id: user.user_id,
        source_key: 'gscloud',
        resource_type: product.value,
        region,
        account_mode: 'platform',
        request_text: `前端一键提交：下载 ${region} ${product.requestLabel}`,
        output_name: `${region}_${product.outputSuffix}`,
        session_id: sessionId
      });
      if (result.auto_started) {
        setNotice('已提交下载任务，系统正在处理。');
      } else if (result.reason === 'waiting_login') {
        setNotice('已创建下载任务，但当前账号状态需要重新确认。');
      } else {
        setNotice('已创建下载任务，当前任务暂未启动自动下载。');
      }
      refreshDashboard();
      refreshJobs();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '提交失败');
    } finally {
      setBusy(false);
    }
  };

  const preflightPlatformJob = async () => {
    if (!user) {
      setNotice('请先登录账号，再验证下载链路。');
      return;
    }
    setPreflightBusy(true);
    try {
      const region = downloadRegion.trim() || '成都市';
      const product = downloadProducts.find((item) => item.value === downloadResourceType) || downloadProducts[0];
      if (product.value === 'dem') {
        setNotice('DEM 使用分幅下载流程，当前预检按钮用于 Landsat、MODIS 和 Sentinel 场景表产品。');
        return;
      }
      const result = await api.preflightDownload({
        user_id: user.user_id,
        source_key: 'gscloud',
        resource_type: product.value,
        region,
        account_mode: 'platform',
        request_text: `预检 ${region} ${product.requestLabel}`,
        max_pages: 1
      });
      if (result.ok) {
        const sceneId = typeof result.scene?.scene_id === 'string' ? result.scene.scene_id : '';
        setNotice(`验证通过：扫描 ${result.pages_scanned || 0} 页，候选 ${result.candidate_count || 0} 条，${sceneId ? `可下载记录 ${sceneId}` : '已定位下载入口'}。`);
      } else {
        setNotice(result.message || '验证未通过，请检查登录态、区域或筛选条件。');
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '验证失败');
    } finally {
      setPreflightBusy(false);
    }
  };

  const exportAll = async () => {
    setBusy(true);
    try {
      const r = await api.exportWorkspace(userId, sessionId, 'all');
      setNotice(`已打包 ${r.file_count} 个成果文件。${r.download_url ? '可在最近成果中下载。' : ''}`);
      refreshDashboard();
      if (r.download_url) await downloadUrl(r.download_url, 'workspace-export.zip');
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '导出失败');
    } finally {
      setBusy(false);
    }
  };

  const downloadUrl = async (url: string | undefined, fallbackName: string) => {
    if (!url) return;
    try {
      await api.downloadAuthenticated(url, fallbackName);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '下载失败');
    }
  };

  const downloadJobArtifact = async (job: DownloadJob) => {
    const ref = jobView(job)?.artifact_refs?.[0];
    if (ref?.artifact_id) {
      const metadata = await api.artifactMetadata(ref.artifact_id, userId, sessionId);
      await downloadUrl(metadata.download_url, metadata.filename || metadata.title || ref.title || jobTitle(job));
      return;
    }
    setNotice('该任务没有可解析的 artifact_id，暂不能提供下载入口。');
  };

  const downloadWorkspaceArtifact = async (artifactId: string | undefined, fallbackName: string) => {
    if (!artifactId) {
      setNotice('该成果缺少 artifact_id，无法通过安全下载解析器下载。');
      return;
    }
    try {
      const metadata = await api.artifactMetadata(artifactId, userId, sessionId);
      await api.downloadArtifactById(artifactId, metadata.filename || metadata.title || fallbackName, userId, sessionId);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '文件已清理、无访问权限或下载链接已失效。');
    }
  };

  const deleteJob = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.deleteDownloadJob(job.job_id, userId, sessionId);
      setJobs(attachManagementViews(result.jobs || [], result.management_views || []));
      setNotice(`已删除下载任务记录：${jobTitle(job)}`);
      refreshDashboard();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '删除任务失败');
    } finally {
      setBusy(false);
    }
  };

  const deleteArtifact = async (artifact: WorkspaceDashboard['artifacts'][number]) => {
    setBusy(true);
    try {
      const result = await api.deleteWorkspaceArtifact({
        user_id: userId,
        session_id: sessionId,
        artifact_id: artifact.artifact_id || '',
        path: artifact.path || ''
      });
      setDashboard(result.dashboard);
      setNotice(`已删除结果文件：${artifact.filename || artifact.name || artifact.title || artifact.artifact_id || 'artifact'}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '删除结果文件失败');
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.cancelDownloadJob(job.job_id, userId, '用户在前端取消任务。', sessionId);
      setJobs(attachManagementViews(result.jobs || [], result.management_views || []));
      setNotice(`已取消下载任务：${jobTitle(job)}`);
      refreshDashboard();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '取消任务失败');
    } finally {
      setBusy(false);
    }
  };

  const retryJob = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.retryDownloadJob(job.job_id, userId, sessionId);
      setJobs(attachManagementViews(result.jobs || [], result.management_views || []));
      setNotice(result.auto_started ? '已创建重试任务并开始后台下载。' : `已创建重试任务：${result.reason || '等待处理'}`);
      refreshDashboard();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '重试任务失败');
    } finally {
      setBusy(false);
    }
  };

  const checkLoginHealth = async () => {
    if (!user) {
      setNotice('请先登录账号，再检查下载登录态。');
      return;
    }
    setBusy(true);
    try {
      const result = await api.loginHealth(user.user_id, 'gscloud', 'platform');
      const health = result.login_health || {};
      setNotice(health.ok ? 'GSCloud 平台账号登录态可用。' : `GSCloud 登录态不可用：${String(health.reason || health.detail || '需要重新登录')}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '检查登录态失败');
    } finally {
      setBusy(false);
    }
  };

  const inspectJobLog = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.downloadJobLog(userId, job.job_id, sessionId);
      const view = result.management_view;
      const sceneCount = result.diagnostic_event_views?.scene_jobs?.length || 0;
      const tileCount = result.diagnostic_event_views?.tile_jobs?.length || 0;
      const auditCount = result.diagnostic_event_views?.audit_events?.length || 0;
      await api.downloadJobLogFile(userId, job.job_id, sessionId);
      setNotice(`任务日志：状态 ${view?.status || '--'}，场景日志 ${sceneCount} 条，分幅日志 ${tileCount} 条，审计记录 ${auditCount} 条。`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '读取任务日志失败');
    } finally {
      setBusy(false);
    }
  };

  const counts = dashboard?.dataset_type_counts || {};
  const artifacts = dashboard?.artifacts?.slice(0, 4) || [];
  const runtime = dashboard?.runtime_status || {};
  const recentJobs = jobs.slice(0, 5);
  const runningJobs = jobs.filter((job) => jobStatus(job) === 'running');
  const waitingJobs = jobs.filter((job) => ['awaiting_confirmation', 'blocked'].includes(jobStatus(job)));

  return (
    <motion.aside
      layout
      className={cn('no-drag fixed bottom-3 top-3 z-30 w-[min(360px,calc(100vw-1.5rem))] sm:bottom-4 sm:top-8', side === 'right' ? 'right-3 sm:right-4' : 'left-3 sm:left-[470px]')}
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 22, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
    >
      <GlassCard className="flex h-full min-h-0 flex-col overflow-hidden p-0">
        <div className="shrink-0 border-b border-white/45 bg-white/68 px-4 py-4 shadow-[0_12px_34px_rgba(15,23,42,.05)] backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/48">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 text-lg font-black tracking-tight"><Layers3 size={20} strokeWidth={1.5} /> 数据与工具</div>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">观测数据、遥感产品、模型成果与下载任务</p>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setSide(side === 'right' ? 'left' : 'right')} className="glass-button h-10 w-10 rounded-2xl p-0" title="切换停靠位置"><ScanSearch size={18} strokeWidth={1.5} /></button>
              <button onClick={onClose} className="glass-button h-10 w-10 rounded-2xl p-0" title="隐藏数据与工具"><PanelRightClose size={18} strokeWidth={1.5} /></button>
            </div>
          </div>

          <SegmentedControl value={basemap} onChange={(v) => setBasemap(v as Basemap)} options={[{ label: '矢量', value: 'standard' }, { label: '影像', value: 'satellite' }, { label: '地形', value: 'terrain' }, { label: '暗色', value: 'dark' }]} />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-10">
          <div className="mt-4 grid grid-cols-4 gap-2">
            {[['矢量', counts.vector || 0], ['栅格', counts.raster || 0], ['表格', counts.table || 0], ['文档', counts.document || 0]].map(([k, v]) => (
              <div key={String(k)} className="rounded-2xl border border-white/45 bg-white/58 p-2 text-center shadow-sm dark:border-white/10 dark:bg-white/5">
                <div className="text-base font-black text-ocean dark:text-cyan-glow">{String(v)}</div>
                <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">{String(k)}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-[18px] border border-white/45 bg-white/58 p-3 shadow-sm dark:border-white/10 dark:bg-slate-950/30">
            <div className="mb-1 flex items-center gap-2 text-sm font-black"><BarChart3 size={16} strokeWidth={1.5} /> 运行状态</div>
            <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{String(runtime.label || '就绪')} · {String(runtime.detail || '等待任务')}</p>
            <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-200/80 ring-1 ring-slate-900/5 dark:bg-white/10 dark:ring-white/5">
              <div className="h-full rounded-full bg-gradient-to-r from-ocean to-cyan-glow transition-all duration-500" style={{ width: `${Number(runtime.progress || 0)}%` }} />
            </div>
            {runningJobs.length > 0 && (
              <div className="mt-3 rounded-2xl border border-cyan-glow/25 bg-cyan-glow/10 px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-200">
                {runningJobs.length} 个下载任务正在后台运行，面板会自动刷新完成状态。
              </div>
            )}
            {runningJobs.length === 0 && waitingJobs.length > 0 && (
              <div className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-300/10 px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-200">
                {waitingJobs.length} 个下载任务处于等待状态，尚未在后台下载。
              </div>
            )}
          </div>

          {recentJobs.length > 0 && (
            <div className="mt-4 rounded-[18px] border border-white/45 bg-white/58 p-3 shadow-sm dark:border-white/10 dark:bg-slate-950/30">
              <div className="mb-2 flex items-center gap-2 text-sm font-black"><Download size={16} strokeWidth={1.5} /> 下载任务</div>
              <div className="space-y-2">
                {recentJobs.map((job) => {
                  const status = jobStatus(job);
                  const done = status === 'succeeded';
                  const failed = status === 'failed';
                  const active = canJob(job, 'cancel');
                  const retryable = canJob(job, 'retry');
                  const deletable = !active;
                  return (
                    <div key={job.job_id} className={cn('rounded-2xl border px-3 py-2 text-xs shadow-sm transition hover:-translate-y-0.5', done ? 'border-emerald-300/35 bg-emerald-400/10' : failed ? 'border-coral/30 bg-coral/10' : 'border-white/35 bg-white/45 dark:border-white/10 dark:bg-white/5')}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-black text-slate-700 dark:text-slate-100">{jobTitle(job)}</div>
                          <div className="mt-0.5 text-slate-500 dark:text-slate-400">{status || 'unknown'} · {jobStage(job)} · {Number(jobProgress(job) || 0)}%</div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {done && canJob(job, 'view_artifacts') && (
                            <button type="button" onClick={() => downloadJobArtifact(job)} className="rounded-full bg-gradient-to-r from-ocean to-cyan-glow px-3 py-1.5 font-black text-white shadow-glow">下载</button>
                          )}
                          {active && (
                            <button
                              onClick={() => cancelJob(job)}
                              disabled={busy}
                              className="grid h-8 w-8 place-items-center rounded-full border border-white/35 bg-white/45 text-amber-600 transition hover:bg-white/70 disabled:opacity-50 dark:border-white/10 dark:bg-white/10"
                              title="取消任务并释放预占额度"
                            >
                              <XCircle size={14} strokeWidth={1.8} />
                            </button>
                          )}
                          {retryable && (
                            <button
                              onClick={() => retryJob(job)}
                              disabled={busy}
                              className="grid h-8 w-8 place-items-center rounded-full border border-white/35 bg-white/45 text-ocean transition hover:bg-white/70 disabled:opacity-50 dark:border-white/10 dark:bg-white/10"
                              title="按原条件重试任务"
                            >
                              <RotateCcw size={14} strokeWidth={1.8} />
                            </button>
                          )}
                          <button
                            onClick={() => inspectJobLog(job)}
                            disabled={busy}
                            className="grid h-8 w-8 place-items-center rounded-full border border-white/35 bg-white/45 text-slate-500 transition hover:bg-white/70 disabled:opacity-50 dark:border-white/10 dark:bg-white/10"
                            title="查看任务日志摘要"
                          >
                            <ScanSearch size={14} strokeWidth={1.8} />
                          </button>
                          <button
                            onClick={() => deleteJob(job)}
                            disabled={busy || !deletable}
                            className="grid h-8 w-8 place-items-center rounded-full border border-white/35 bg-white/45 text-coral transition hover:bg-white/70 disabled:opacity-50 dark:border-white/10 dark:bg-white/10"
                            title={deletable ? '删除这条下载任务记录' : '任务进行中，请先取消'}
                          >
                            <Trash2 size={14} strokeWidth={1.8} />
                          </button>
                        </div>
                      </div>
                      {(jobState(job, 'pages_scanned') || jobState(job, 'candidate_count') || jobState(job, 'current_scene')) && (
                        <div className="mt-1 text-slate-500 dark:text-slate-400">
                          扫描 {jobState(job, 'pages_scanned') || 0} 页 · 候选 {jobState(job, 'candidate_count') || 0} 条 · 已选 {jobState(job, 'selected_count') || 0} 条 · 已下 {jobState(job, 'downloaded_count') || 0} 个
                          {jobState(job, 'current_scene') ? ` · 当前 ${jobState(job, 'current_scene')}` : ''}
                        </div>
                      )}
                      {jobView(job)?.user_message && <div className="mt-1 text-coral">{jobView(job)?.user_message}</div>}
                      {jobView(job)?.warnings?.length ? <div className="mt-1 text-amber-600 dark:text-amber-300">{jobView(job)?.warnings?.[0]}</div> : null}
                      {failed && jobView(job)?.error_title && !jobView(job)?.user_message && <div className="mt-1 text-coral">{jobView(job)?.error_title}</div>}
                      {done && !canJob(job, 'view_artifacts') && <div className="mt-1 text-slate-500 dark:text-slate-400">已完成，结果正在整理。</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <ResearchWorkflowPanel onRunAction={onRunWorkflowAction} />

          <LocalLibraryPanel userId={userId} onImported={refreshDashboard} />

          <div className="mt-4 space-y-2">
            {layers.map((layer) => {
              const active = hasLayerVisibility(layer.id) ? layerVisibility[layer.id] : layer.active;
              const locatableLayerId = hasLayerVisibility(layer.id) ? layer.id : null;
              return (
                <motion.div key={layer.id} whileHover={{ x: 3 }} className={cn('group relative grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 rounded-[18px] border border-white/45 bg-white/34 p-2.5 shadow-sm transition hover:bg-white/62 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/8', active && 'bg-white/68 ring-1 ring-cyan-300/25 dark:bg-white/8')}>
                  {active && <motion.span layoutId="layer-active" className="absolute left-0 top-3 h-10 w-1 rounded-full bg-gradient-to-b from-ocean to-cyan-glow" />}
                  <LayerThumb accent={layer.accent} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-black">{layer.name}</div>
                    <div className="truncate text-xs text-slate-500 dark:text-slate-400">{layer.desc}</div>
                  </div>
                  {locatableLayerId && (
                    <button type="button" onClick={() => onLayerLocate(locatableLayerId)} className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/45 bg-white/58 text-slate-500 shadow-sm transition hover:-translate-y-0.5 hover:bg-white/80 dark:border-white/10 dark:bg-white/10" title="定位到图层">
                      <Map size={14} strokeWidth={1.7} />
                    </button>
                  )}
                  <GlowSwitch
                    active={active}
                    onClick={() => {
                      if (hasLayerVisibility(layer.id)) onLayerToggle(layer.id);
                      setLayers((items) => items.map((x) => x.id === layer.id ? { ...x, active: !active } : x));
                    }}
                  />
                </motion.div>
              );
            })}
          </div>

          <div className="mt-4 rounded-[18px] border border-white/45 bg-white/58 p-3 shadow-sm dark:border-white/10 dark:bg-slate-950/30">
            <div className="mb-2 flex items-center gap-2 text-sm font-black"><Database size={16} strokeWidth={1.5} /> 数据下载</div>
            <select
              value={downloadResourceType}
              onChange={(event) => setDownloadResourceType(event.target.value)}
              className="mt-3 w-full rounded-2xl border border-white/55 bg-white/75 px-3 py-2 text-sm font-semibold text-slate-700 outline-none shadow-sm transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-200/35 dark:border-white/10 dark:bg-slate-900 dark:text-slate-100"
              aria-label="选择下载产品"
            >
              {downloadProducts.map((product) => (
                <option key={product.value} value={product.value}>{product.label}</option>
              ))}
            </select>
            <input
              value={downloadRegion}
              onChange={(event) => setDownloadRegion(event.target.value)}
              className="mt-3 w-full rounded-2xl border border-white/55 bg-white/75 px-3 py-2 text-sm font-semibold text-slate-700 outline-none shadow-sm transition placeholder:text-slate-400 focus:border-cyan-300 focus:ring-4 focus:ring-cyan-200/35 dark:border-white/10 dark:bg-white/10 dark:text-slate-100"
              placeholder="输入下载区域，例如 成都市 / 四川省"
            />
            <button onClick={preflightPlatformJob} disabled={preflightBusy || busy} className="glass-button mt-3 w-full gap-2 rounded-2xl text-sm font-black disabled:opacity-60"><ScanSearch size={16} strokeWidth={1.5} /> {preflightBusy ? '验证中...' : '先验证可下载'}</button>
            <button onClick={checkLoginHealth} disabled={busy} className="glass-button mt-2 w-full gap-2 rounded-2xl text-sm font-black disabled:opacity-60"><ScanSearch size={16} strokeWidth={1.5} /> 检查 GSCloud 登录态</button>
            <button onClick={submitPlatformJob} disabled={busy || preflightBusy} className="primary-button mt-2 w-full gap-2 disabled:opacity-60"><Map size={16} strokeWidth={1.5} /> {busy ? '处理中...' : '使用平台账号下载数据'}</button>
            <button onClick={exportAll} disabled={busy} className="glass-button mt-2 w-full gap-2 rounded-2xl text-sm font-black disabled:opacity-60"><FileArchive size={16} strokeWidth={1.5} /> 打包导出成果</button>
            {notice && <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{notice}</p>}
          </div>

          {artifacts.filter((item) => item.artifact_id).length > 0 && (
            <div className="mt-4 rounded-[18px] border border-white/45 bg-white/58 p-3 shadow-sm dark:border-white/10 dark:bg-slate-950/30">
              <div className="mb-2 flex items-center gap-2 text-sm font-black"><Download size={16} strokeWidth={1.5} /> 最近成果</div>
              <div className="space-y-2">
                {artifacts.filter((item) => item.artifact_id).map((item) => {
                  const safeName = item.filename || item.name || item.title || item.artifact_id || '成果文件';
                  const stableKey = item.artifact_id || safeName;
                  return (
                  <div key={stableKey} className="flex items-center justify-between gap-2 rounded-2xl border border-white/35 bg-white/48 px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-white/72 dark:border-white/10 dark:bg-white/5 dark:text-slate-300">
                    <button type="button" onClick={() => downloadWorkspaceArtifact(item.artifact_id, safeName)} className="min-w-0 flex-1 truncate text-left">
                    {safeName}
                    </button>
                    <button type="button" onClick={() => deleteArtifact(item)} disabled={busy} className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-coral transition hover:bg-white/60 disabled:opacity-50" title="删除结果文件">
                      <Trash2 size={14} strokeWidth={1.8} />
                    </button>
                  </div>
                )})}
              </div>
            </div>
          )}
        </div>
      </GlassCard>
    </motion.aside>
  );
}
