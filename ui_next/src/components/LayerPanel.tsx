import { motion } from 'framer-motion';
import { BarChart3, Database, Download, FileArchive, Layers3, Map, PanelRightClose, RotateCcw, ScanSearch, Trash2, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { GlassCard } from './GlassCard';
import { LocalLibraryPanel } from './LocalLibraryPanel';
import { ResearchWorkflowPanel } from './ResearchWorkflowPanel';
import { SegmentedControl } from './SegmentedControl';
import { CommercialUser, DownloadJob, WorkspaceDashboard, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { LayerOpacity, LayerVisibility } from './mapLayerPolicy';
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
  { value: 'modnd1d_ndvi_daily', label: 'MODND1D NDVI 每天产品', outputSuffix: 'modnd1d_ndvi', requestLabel: 'MODND1D NDVI 每天产品' },
  { value: 'modl1d_lst_daily', label: 'MODL1D 1KM 地表温度', outputSuffix: 'modl1d_lst', requestLabel: 'MODL1D 中国 1KM 地表温度每天产品' },
  { value: 'modev1f_evi_5day', label: 'MODEV1F 250M EVI 五天合成', outputSuffix: 'modev1f_evi', requestLabel: 'MODEV1F 中国 250M EVI 五天合成产品' },
  { value: 'mod021km_surface_reflectance', label: 'MOD021KM 1KM 地表反射率', outputSuffix: 'mod021km_reflectance', requestLabel: 'MOD021KM 1KM 地表反射率' },
  { value: 'sentinel2_msi', label: 'Sentinel-2 MSI', outputSuffix: 'sentinel2_msi', requestLabel: 'Sentinel-2 MSI 数据' }
];

function LayerThumb({ accent }: { accent: string }) {
  return (
    <div className="relative h-12 w-14 shrink-0 overflow-hidden rounded-2xl border border-white/40 bg-white/40 dark:border-white/10 dark:bg-white/5">
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
      className={cn('relative h-7 w-12 shrink-0 overflow-hidden rounded-full border transition', active ? 'border-cyan-glow/50 bg-cyan-glow/30 shadow-glow' : 'border-white/40 bg-slate-400/15 dark:border-white/10')}
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

function hasLayerOpacity(id: string): id is keyof LayerOpacity {
  return id === 'stations' || id === 'boundary' || id === 'dem' || id === 'soil' || id === 'draw';
}

export function LayerPanel({
  user,
  basemap,
  setBasemap,
  onClose,
  layerVisibility,
  layerOpacity,
  onLayerToggle,
  onLayerOpacityChange,
  onLayerLocate,
  onRunWorkflowAction
}: {
  user: CommercialUser | null;
  basemap: Basemap;
  setBasemap: (value: Basemap) => void;
  onClose?: () => void;
  layerVisibility: LayerVisibility;
  layerOpacity: LayerOpacity;
  onLayerToggle: (id: keyof LayerVisibility) => void;
  onLayerOpacityChange: (id: keyof LayerOpacity, value: number) => void;
  onLayerLocate: (id: keyof LayerOpacity) => void;
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
    api.dashboard(userId).then(setDashboard).catch(() => setDashboard(null));
  };

  const refreshJobs = () => {
    api.jobs(userId)
      .then((r) => {
        const nextJobs = r.jobs || [];
        setJobs(nextJobs);
        if (!jobsInitializedRef.current) {
          nextJobs
            .filter((job) => job.status === 'completed')
            .forEach((job) => completedSeenRef.current.add(job.job_id));
          jobsInitializedRef.current = true;
          return;
        }
        const latestCompleted = nextJobs.find((job) => job.status === 'completed' && !completedSeenRef.current.has(job.job_id));
        if (latestCompleted) {
          completedSeenRef.current.add(latestCompleted.job_id);
          setNotice(`下载任务已完成：${latestCompleted.output_name || latestCompleted.job_id}。可在“下载任务”中查看或下载结果。`);
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
  }, [userId]);

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
        output_name: `${region}_${product.outputSuffix}`
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
      const r = await api.exportWorkspace(userId, 'all');
      setNotice(`已打包 ${r.file_count} 个成果文件。${r.download_url ? '可在最近成果中下载。' : ''}`);
      refreshDashboard();
      if (r.download_url) window.open(r.download_url, '_blank');
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '导出失败');
    } finally {
      setBusy(false);
    }
  };

  const deleteJob = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.deleteDownloadJob(job.job_id, userId);
      setJobs(result.jobs || []);
      setNotice(`已删除下载任务记录：${job.output_name || job.job_id}`);
      refreshDashboard();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '删除任务失败');
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async (job: DownloadJob) => {
    setBusy(true);
    try {
      const result = await api.cancelDownloadJob(job.job_id, userId, '用户在前端取消任务。');
      setJobs(result.jobs || []);
      setNotice(`已取消下载任务：${job.output_name || job.job_id}`);
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
      const result = await api.retryDownloadJob(job.job_id, userId);
      setJobs(result.jobs || []);
      setNotice(result.auto_started ? '已创建重试任务并开始后台下载。' : `已创建重试任务：${result.reason || '等待处理'}`);
      refreshDashboard();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '重试任务失败');
    } finally {
      setBusy(false);
    }
  };

  const counts = dashboard?.dataset_type_counts || {};
  const artifacts = dashboard?.artifacts?.slice(0, 4) || [];
  const runtime = dashboard?.runtime_status || {};
  const recentJobs = jobs.slice(0, 5);
  const runningJobs = jobs.filter((job) => job.status === 'running');
  const waitingJobs = jobs.filter((job) => job.status === 'queued' || job.status === 'waiting_login' || job.status === 'waiting_manual');

  return (
    <motion.aside
      layout
      className={cn('no-drag fixed top-8 z-30 w-[min(360px,calc(100vw-1.5rem))]', side === 'right' ? 'right-3 sm:right-4' : 'left-3 sm:left-[470px]')}
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 22, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
    >
      <GlassCard className="max-h-[calc(100vh-4rem)] overflow-hidden p-0">
        <div className="sticky top-0 z-10 border-b border-white/30 bg-white/45 px-4 py-4 backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/35">
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

        <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 pb-4">
          <div className="mt-4 grid grid-cols-4 gap-2">
            {[['矢量', counts.vector || 0], ['栅格', counts.raster || 0], ['表格', counts.table || 0], ['文档', counts.document || 0]].map(([k, v]) => (
              <div key={String(k)} className="rounded-2xl border border-white/30 bg-white/35 p-2 text-center dark:border-white/10 dark:bg-white/5">
                <div className="text-base font-black text-ocean dark:text-cyan-glow">{String(v)}</div>
                <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">{String(k)}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
            <div className="mb-3 flex items-center gap-2 text-sm font-black"><Layers3 size={16} strokeWidth={1.5} /> 图层透明度</div>
            {([
              ['stations', '站点观测'],
              ['boundary', '研究区边界'],
              ['dem', 'DEM / 高程'],
              ['soil', '土壤水分'],
              ['draw', '绘制结果']
            ] as Array<[keyof LayerOpacity, string]>).map(([id, label]) => (
              <label key={id} className="mb-2 grid grid-cols-[72px_minmax(0,1fr)_34px] items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
                <span>{label}</span>
                <input type="range" min={0.15} max={1} step={0.05} value={layerOpacity[id]} onChange={(event) => onLayerOpacityChange(id, Number(event.target.value))} />
                <span className="text-right">{Math.round(layerOpacity[id] * 100)}%</span>
              </label>
            ))}
          </div>

          <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
            <div className="mb-3 flex items-center gap-2 text-sm font-black"><Layers3 size={16} strokeWidth={1.5} /> 图例</div>
            <div className="grid grid-cols-2 gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
              {[
                ['站点偏低', '#f59e0b'],
                ['站点中等', '#22D3EE'],
                ['站点偏高', '#10b981'],
                ['研究区边界', '#22D3EE'],
                ['DEM / 高程', '#38bdf8'],
                ['土壤水分', '#10b981']
              ].map(([label, color]) => (
                <div key={label} className="flex items-center gap-2 rounded-xl bg-white/35 px-2 py-1.5 dark:bg-white/5">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
            <div className="mb-1 flex items-center gap-2 text-sm font-black"><BarChart3 size={16} strokeWidth={1.5} /> 运行状态</div>
            <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{String(runtime.label || '就绪')} · {String(runtime.detail || '等待任务')}</p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200/70 dark:bg-white/10">
              <div className="h-full rounded-full bg-gradient-to-r from-ocean to-cyan-glow transition-all" style={{ width: `${Number(runtime.progress || 0)}%` }} />
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
            <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
              <div className="mb-2 flex items-center gap-2 text-sm font-black"><Download size={16} strokeWidth={1.5} /> 下载任务</div>
              <div className="space-y-2">
                {recentJobs.map((job) => {
                  const done = job.status === 'completed';
                  const failed = job.status === 'failed';
                  const active = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_login' || job.status === 'waiting_manual';
                  const retryable = failed || job.status === 'canceled' || job.status === 'waiting_login' || job.status === 'waiting_manual';
                  const deletable = !active;
                  return (
                    <div key={job.job_id} className={cn('rounded-2xl border px-3 py-2 text-xs', done ? 'border-emerald-300/35 bg-emerald-400/10' : failed ? 'border-coral/30 bg-coral/10' : 'border-white/25 bg-white/25 dark:border-white/10 dark:bg-white/5')}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-black text-slate-700 dark:text-slate-100">{job.output_name || job.job_id}</div>
                          <div className="mt-0.5 text-slate-500 dark:text-slate-400">{job.status || 'unknown'} · {job.stage || '--'} · {Number(job.progress || 0)}%</div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {done && job.download_url && (
                            <a href={job.download_url} target="_blank" rel="noreferrer" className="rounded-full bg-gradient-to-r from-ocean to-cyan-glow px-3 py-1.5 font-black text-white shadow-glow">下载</a>
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
                            onClick={() => deleteJob(job)}
                            disabled={busy || !deletable}
                            className="grid h-8 w-8 place-items-center rounded-full border border-white/35 bg-white/45 text-coral transition hover:bg-white/70 disabled:opacity-50 dark:border-white/10 dark:bg-white/10"
                            title={deletable ? '删除这条下载任务记录' : '任务进行中，请先取消'}
                          >
                            <Trash2 size={14} strokeWidth={1.8} />
                          </button>
                        </div>
                      </div>
                      {(job.pages_scanned || job.candidate_count || job.current_scene) && (
                        <div className="mt-1 text-slate-500 dark:text-slate-400">
                          扫描 {job.pages_scanned || 0} 页 · 候选 {job.candidate_count || 0} 条 · 已选 {job.selected_count || 0} 条 · 已下 {job.downloaded_count || 0} 个
                          {job.current_scene ? ` · 当前 ${job.current_scene}` : ''}
                        </div>
                      )}
                      {job.failure_diagnostic?.user_message && <div className="mt-1 text-coral">{job.failure_diagnostic.user_message}</div>}
                      {job.scan_stop_reason && <div className="mt-1 text-slate-500 dark:text-slate-400">扫描停止：{job.scan_stop_reason}</div>}
                      {job.quota_reserved ? <div className="mt-1 text-amber-600 dark:text-amber-300">已预占 1 次平台账号额度，失败或取消会自动释放。</div> : null}
                      {job.retried_from_job_id && <div className="mt-1 text-slate-500 dark:text-slate-400">重试来源：{job.retried_from_job_id}</div>}
                      {job.artifact_quality?.length ? (
                        <div className={cn('mt-1', job.artifact_quality.every((item) => item.ok !== false) ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300')}>
                          成果质量：{job.artifact_quality.every((item) => item.ok !== false) ? '已通过基础检查' : '需要检查文件或范围'}
                        </div>
                      ) : null}
                      {failed && job.error_message && <div className="mt-1 text-coral">{job.error_message}</div>}
                      {done && !job.download_url && <div className="mt-1 text-slate-500 dark:text-slate-400">已完成，结果正在整理。</div>}
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
              const opacityLayerId = hasLayerOpacity(layer.id) ? layer.id : null;
              return (
                <motion.div key={layer.id} whileHover={{ x: 3 }} className={cn('group relative grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 rounded-[18px] border border-white/30 p-2.5 transition hover:bg-white/45 dark:border-white/10 dark:hover:bg-white/5', active && 'bg-white/45 dark:bg-white/5')}>
                  {active && <motion.span layoutId="layer-active" className="absolute left-0 top-3 h-10 w-1 rounded-full bg-gradient-to-b from-ocean to-cyan-glow" />}
                  <LayerThumb accent={layer.accent} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-black">{layer.name}</div>
                    <div className="truncate text-xs text-slate-500 dark:text-slate-400">{layer.desc}</div>
                  </div>
                  {opacityLayerId && (
                    <button type="button" onClick={() => onLayerLocate(opacityLayerId)} className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/35 bg-white/45 text-slate-500 transition hover:bg-white/70 dark:border-white/10 dark:bg-white/10" title="定位到图层">
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

          <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
            <div className="mb-2 flex items-center gap-2 text-sm font-black"><Database size={16} strokeWidth={1.5} /> 数据下载</div>
            <select
              value={downloadResourceType}
              onChange={(event) => setDownloadResourceType(event.target.value)}
              className="mt-3 w-full rounded-2xl border border-white/35 bg-white/55 px-3 py-2 text-sm font-semibold text-slate-700 outline-none transition focus:border-cyan-300 dark:border-white/10 dark:bg-slate-900 dark:text-slate-100"
              aria-label="选择下载产品"
            >
              {downloadProducts.map((product) => (
                <option key={product.value} value={product.value}>{product.label}</option>
              ))}
            </select>
            <input
              value={downloadRegion}
              onChange={(event) => setDownloadRegion(event.target.value)}
              className="mt-3 w-full rounded-2xl border border-white/35 bg-white/55 px-3 py-2 text-sm font-semibold text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 dark:border-white/10 dark:bg-white/10 dark:text-slate-100"
              placeholder="输入下载区域，例如 成都市 / 四川省"
            />
            <button onClick={preflightPlatformJob} disabled={preflightBusy || busy} className="glass-button mt-3 w-full gap-2 rounded-2xl text-sm font-black disabled:opacity-60"><ScanSearch size={16} strokeWidth={1.5} /> {preflightBusy ? '验证中...' : '先验证可下载'}</button>
            <button onClick={submitPlatformJob} disabled={busy || preflightBusy} className="primary-button mt-2 w-full gap-2 disabled:opacity-60"><Map size={16} strokeWidth={1.5} /> {busy ? '处理中...' : '使用平台账号下载数据'}</button>
            <button onClick={exportAll} disabled={busy} className="glass-button mt-2 w-full gap-2 rounded-2xl text-sm font-black disabled:opacity-60"><FileArchive size={16} strokeWidth={1.5} /> 打包导出成果</button>
            {notice && <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{notice}</p>}
          </div>

          {artifacts.length > 0 && (
            <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
              <div className="mb-2 flex items-center gap-2 text-sm font-black"><Download size={16} strokeWidth={1.5} /> 最近成果</div>
              <div className="space-y-2">
                {artifacts.map((item, i) => (
                  <a key={`${item.path}-${i}`} href={item.download_url || '#'} target="_blank" rel="noreferrer" className="block rounded-2xl border border-white/25 bg-white/30 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-white/60 dark:border-white/10 dark:bg-white/5 dark:text-slate-300">
                    {item.name || item.path.split(/[\\/]/).pop() || '成果文件'}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      </GlassCard>
    </motion.aside>
  );
}
