import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  Archive,
  BarChart3,
  Bot,
  ChevronRight,
  ClipboardList,
  Database,
  Download,
  FileArchive,
  FileText,
  FolderOpen,
  Home,
  Layers3,
  ListChecks,
  Loader2,
  Map,
  MessageSquare,
  Play,
  RefreshCcw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  XCircle
} from 'lucide-react';
import { AuthPanel } from './AuthPanel';
import { CapabilityManagementPanel } from './CapabilityManagementPanel';
import { ChatWorkspace, type ExternalPromptCommand } from './ChatPanel';
import { GSCloudAccountPanel } from './GSCloudAccountPanel';
import { LocalLibraryPanel } from './LocalLibraryPanel';
import { api, CommercialUser, DiagnosticEventView, DownloadJob, DownloadManagementView, ResultPanel, WorkspaceDashboard } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { ChatContextPayload } from '@/lib/chatContext';
import type { ParsedMapTextCommand } from './mapTextCommands';
import {
  ConsoleArtifact,
  ProductTaskTone,
  formatPercent,
  groupArtifacts,
  normalizeTaskStatus,
  summarizeJobs
} from './productConsoleData';

type ConsoleTab = 'overview' | 'chat' | 'create' | 'tasks' | 'logs' | 'results' | 'data' | 'settings';
type ConsoleNavItem = {
  id: ConsoleTab | 'map-workbench';
  label: string;
  icon: typeof Home;
  action?: 'openMap';
};

type ProductConsoleProps = {
  user: CommercialUser | null;
  setUser: (user: CommercialUser | null) => void;
  sessionId?: string;
  resultPanel?: ResultPanel | null;
  onOpenChat?: () => void;
  onOpenMap?: () => void;
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  externalPrompt?: ExternalPromptCommand | null;
  onResultPanel?: (panel: ResultPanel) => void;
  onSessionChange?: (sessionId: string) => void;
  chatContext?: ChatContextPayload;
};

type DownloadProduct = {
  value: string;
  label: string;
  outputSuffix: string;
  requestLabel: string;
};

type JobLogData = {
  management_view?: DownloadManagementView;
  diagnostic_event_views?: {
    scene_jobs?: DiagnosticEventView[];
    tile_jobs?: DiagnosticEventView[];
    audit_events?: DiagnosticEventView[];
  };
};

const navItems: ConsoleNavItem[] = [
  { id: 'chat', label: '智能聊天', icon: MessageSquare },
  { id: 'overview', label: '总览', icon: Home },
  { id: 'map-workbench', label: '地图工作台', icon: Map, action: 'openMap' },
  { id: 'create', label: '新建任务', icon: Play },
  { id: 'tasks', label: '任务中心', icon: ClipboardList },
  { id: 'logs', label: '运行日志', icon: TerminalSquare },
  { id: 'results', label: '结果文件', icon: FolderOpen },
  { id: 'data', label: '数据资产', icon: Database },
  { id: 'settings', label: '设置', icon: Settings }
];

const capabilityCards = [
  {
    title: '数据下载',
    description: '支持 GSCloud、DEM、Landsat、Sentinel-2、MODIS 等数据任务。',
    icon: Download
  },
  {
    title: '任务执行',
    description: '把下载、预检、处理、打包纳入统一任务生命周期。',
    icon: ListChecks
  },
  {
    title: '日志诊断',
    description: '集中查看阶段日志、场景日志、分幅日志和审计事件。',
    icon: TerminalSquare
  },
  {
    title: '结果导出',
    description: '统一管理成果文件、指标、图表、地图图层和导出包。',
    icon: FileArchive
  }
];

const downloadProducts: DownloadProduct[] = [
  { value: 'dem', label: 'DEM / 高程数据', outputSuffix: 'dem', requestLabel: 'DEM 数据' },
  { value: 'landsat8_oli_tirs', label: 'Landsat 8 OLI_TIRS', outputSuffix: 'landsat8', requestLabel: 'Landsat 8 OLI_TIRS 数据' },
  { value: 'sentinel2_msi', label: 'Sentinel-2 MSI', outputSuffix: 'sentinel2_msi', requestLabel: 'Sentinel-2 MSI 数据' },
  { value: 'modnd1t_ndvi_10day', label: 'MODND1T NDVI 旬合成', outputSuffix: 'modnd1t_ndvi', requestLabel: 'MODND1T 中国 500M NDVI 旬合成产品' },
  { value: 'modl1t_lst_composite', label: 'MODLT1T 地表温度旬合成', outputSuffix: 'modl1t_lst', requestLabel: 'MODLT1T 中国 1KM 地表温度旬合成产品' },
  { value: 'modev1t_evi_10day', label: 'MODEV1T 250M EVI 旬合成', outputSuffix: 'modev1t_evi', requestLabel: 'MODEV1T 中国 250M EVI 旬合成产品' },
  { value: 'mod021km_surface_reflectance', label: 'MOD021KM 1KM 地表反射率', outputSuffix: 'mod021km_reflectance', requestLabel: 'MOD021KM 1KM 地表反射率' }
];

const toneStyles: Record<ProductTaskTone, string> = {
  idle: 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300',
  waiting: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200',
  running: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-200',
  blocked: 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900/70 dark:bg-orange-950/35 dark:text-orange-200',
  succeeded: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/35 dark:text-emerald-200',
  failed: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/35 dark:text-rose-200',
  canceled: 'border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400'
};

function StatusBadge({ status }: { status?: string }) {
  const item = normalizeTaskStatus(status);
  return (
    <span className={cn('inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold shadow-sm', toneStyles[item.tone])}>
      {item.label}
    </span>
  );
}

function ProgressBar({ value = 0, tone = 'running' }: { value?: number; tone?: ProductTaskTone }) {
  const pct = formatPercent(value);
  const color = tone === 'failed' ? 'from-rose-500 to-rose-400' : tone === 'succeeded' ? 'from-emerald-500 to-teal-400' : tone === 'blocked' ? 'from-orange-500 to-amber-400' : 'from-blue-600 to-cyan-400';
  return (
    <div className="h-2.5 overflow-hidden rounded-full bg-slate-200/80 ring-1 ring-slate-900/5 dark:bg-slate-800 dark:ring-white/5">
      <div className={cn('h-full rounded-full bg-gradient-to-r transition-all duration-500 ease-out', color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function EmptyState({ icon: Icon, title, description, action }: { icon: typeof FileText; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300/90 bg-white/80 p-7 text-center shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/70">
      <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-cyan-50 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300">
        <Icon size={26} strokeWidth={1.6} />
      </div>
      <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</div>
      <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

function LoadingState({ label = '正在加载' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/85 px-4 py-3 text-sm font-semibold text-slate-600 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
      <Loader2 className="animate-spin text-cyan-600" size={16} />
      {label}
    </div>
  );
}

function StateMessage({ tone, children }: { tone: 'success' | 'error' | 'info'; children: ReactNode }) {
  const styles = {
    success: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200',
    error: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/35 dark:text-rose-200',
    info: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/35 dark:text-blue-200'
  }[tone];
  return <div className={cn('rounded-2xl border px-4 py-3 text-sm font-semibold leading-6 shadow-sm', styles)}>{children}</div>;
}

function SectionHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-slate-950 dark:text-slate-50">{title}</h2>
        {description && <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-2xl border border-slate-200/90 bg-white/86 shadow-[0_16px_42px_rgba(15,23,42,.07)] backdrop-blur transition-colors dark:border-slate-800 dark:bg-slate-900/78', className)}>
      {children}
    </section>
  );
}

function MetricCard({ label, value, hint, icon: Icon }: { label: string; value: string | number; hint: string; icon: typeof Activity }) {
  return (
    <Panel className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</div>
          <div className="mt-2 text-2xl font-bold tracking-tight text-slate-950 dark:text-slate-50">{value}</div>
        </div>
        <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 text-blue-700 shadow-inner dark:from-blue-950/45 dark:to-cyan-950/30 dark:text-cyan-200">
          <Icon size={19} strokeWidth={1.7} />
        </div>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">{hint}</p>
    </Panel>
  );
}

function getJobName(job: DownloadJob) {
  return job.management_view?.display_title || job.output_name || job.region || job.resource_type || job.job_id;
}

function jobView(job?: DownloadJob | null): DownloadManagementView | null {
  return job?.management_view || null;
}

function jobTaskId(job: DownloadJob) {
  return jobView(job)?.task_id || job.job_id;
}

function jobStatus(job: DownloadJob) {
  return jobView(job)?.status || job.status || job.state || 'running';
}

function jobProgress(job: DownloadJob) {
  return Number(jobView(job)?.progress ?? job.progress ?? 0);
}

function jobStage(job: DownloadJob) {
  return jobView(job)?.action_state?.stage || job.stage || '--';
}

function jobSourceName(job: DownloadJob) {
  return jobView(job)?.source_name || [job.source_key, job.resource_type, job.region].filter(Boolean).join(' / ') || '--';
}

function jobActions(job: DownloadJob) {
  return jobView(job)?.available_actions || [];
}

function canJob(job: DownloadJob, action: string) {
  const actions = jobActions(job);
  if (actions.length) return actions.includes(action);
  const tone = normalizeTaskStatus(job.status).tone;
  if (action === 'cancel') return tone === 'running' || tone === 'waiting' || tone === 'blocked';
  if (action === 'retry') return tone === 'failed' || tone === 'canceled' || tone === 'blocked';
  if (action === 'view_artifacts') return Boolean(jobView(job)?.artifact_refs?.length);
  return false;
}

function jobUserMessage(job: DownloadJob) {
  return jobView(job)?.user_message || '';
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

function artifactIcon(kind: ConsoleArtifact['kind']) {
  if (kind === 'archive') return Archive;
  if (kind === 'visual') return Layers3;
  if (kind === 'report') return FileText;
  return FileArchive;
}

export function ProductConsole({
  user,
  setUser,
  sessionId,
  resultPanel,
  onOpenChat,
  onOpenMap,
  onMapTextCommand,
  externalPrompt,
  onResultPanel,
  onSessionChange,
  chatContext
}: ProductConsoleProps) {
  const [activeTab, setActiveTab] = useState<ConsoleTab>('overview');
  const [dashboard, setDashboard] = useState<WorkspaceDashboard | null>(null);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [selectedJobId, setSelectedJobId] = useState('');
  const [logData, setLogData] = useState<JobLogData | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [logError, setLogError] = useState('');
  const [busyJobId, setBusyJobId] = useState('');
  const [exporting, setExporting] = useState(false);
  const [downloadRegion, setDownloadRegion] = useState('成都市');
  const [downloadResourceType, setDownloadResourceType] = useState(downloadProducts[0].value);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [outputName, setOutputName] = useState('');
  const [accountMode, setAccountMode] = useState<'platform' | 'own'>('platform');
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightMessage, setPreflightMessage] = useState('');
  const [preflightOk, setPreflightOk] = useState<boolean | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [gscloudLoginMessage, setGscloudLoginMessage] = useState('');
  const [gscloudLoginLoading, setGscloudLoginLoading] = useState(false);
  const userId = user?.user_id || '';

  const refresh = useCallback(async () => {
    setError('');
    if (!userId) {
      setDashboard(null);
      setJobs([]);
      setSelectedJobId('');
      setLoading(false);
      return;
    }
    try {
      const [dashboardData, jobsData] = await Promise.all([
        api.dashboard(userId, sessionId),
        api.jobs(userId, sessionId)
      ]);
      const nextJobs = attachManagementViews([], jobsData.management_views || []);
      setDashboard(dashboardData);
      setJobs(nextJobs);
      if (!selectedJobId && nextJobs[0]?.job_id) setSelectedJobId(nextJobs[0].job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : '读取控制台数据失败');
    } finally {
      setLoading(false);
    }
  }, [selectedJobId, sessionId, userId]);

  useEffect(() => {
    setLoading(true);
    refresh();
    const timer = window.setInterval(refresh, 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const summary = useMemo(() => summarizeJobs(jobs), [jobs]);
  const counts = dashboard?.dataset_type_counts || {};
  const artifacts = useMemo(() => groupArtifacts(dashboard?.artifacts || []), [dashboard]);
  const workspaceSessionLabel = dashboard?.current_session_id || sessionId || chatContext?.session_id || '';
  const workspaceDisplayName = workspaceSessionLabel ? `会话 ${workspaceSessionLabel.slice(0, 12)}` : '默认工作区';
  const selectedJob = useMemo(() => jobs.find((job) => job.job_id === selectedJobId) || jobs[0], [jobs, selectedJobId]);
  const filteredJobs = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return jobs;
    return jobs.filter((job) => [
      job.job_id,
      getJobName(job),
      jobSourceName(job),
      jobStatus(job),
      jobStage(job)
    ].some((value) => String(value || '').toLowerCase().includes(keyword)));
  }, [jobs, query]);

  const product = downloadProducts.find((item) => item.value === downloadResourceType) || downloadProducts[0];
  const region = downloadRegion.trim() || '成都市';
  const defaultOutputName = `${region}_${product.outputSuffix}`;
  const openChatWorkspace = () => {
    setActiveTab('chat');
  };

  const runPreflight = async () => {
    if (!user) {
      setPreflightOk(false);
      setPreflightMessage('请先登录账号，再验证下载链路。');
      return;
    }
    setPreflightLoading(true);
    setPreflightMessage('');
    setPreflightOk(null);
    try {
      if (product.value === 'dem') {
        setPreflightOk(true);
        setPreflightMessage('DEM 使用分幅下载流程，可直接提交任务；如需场景表产品，可对 Landsat、MODIS、Sentinel-2 先执行预检。');
        return;
      }
      const result = await api.preflightDownload({
        user_id: user.user_id,
        session_id: sessionId || chatContext?.session_id,
        source_key: 'gscloud',
        resource_type: product.value,
        region,
        start_date: startDate,
        end_date: endDate,
        account_mode: accountMode,
        request_text: `预检 ${region} ${product.requestLabel}`,
        max_pages: 1
      });
      setPreflightOk(Boolean(result.ok));
      setPreflightMessage(result.ok
        ? `预检通过：扫描 ${result.pages_scanned || 0} 页，候选 ${result.candidate_count || 0} 条。`
        : result.message || '预检未通过，请检查登录态、区域或筛选条件。');
    } catch (e) {
      setPreflightOk(false);
      setPreflightMessage(e instanceof Error ? e.message : '预检失败');
    } finally {
      setPreflightLoading(false);
    }
  };

  const submitTask = async () => {
    if (!user) {
      setPreflightOk(false);
      setPreflightMessage('请先登录账号，再提交下载任务。');
      return;
    }
    setSubmitLoading(true);
    setNotice('');
    try {
      const result = await api.submitDownload({
        user_id: user.user_id,
        source_key: 'gscloud',
        resource_type: product.value,
        region,
        start_date: startDate,
        end_date: endDate,
        account_mode: accountMode,
        request_text: `控制台提交：下载 ${region} ${product.requestLabel}`,
        output_name: outputName.trim() || defaultOutputName,
        session_id: sessionId || chatContext?.session_id
      });
      setNotice(result.auto_started ? '任务已启动，系统正在后台执行。' : `任务已创建：${result.reason || '等待处理'}`);
      await refresh();
      if (result.management_view?.task_id) setSelectedJobId(result.management_view.task_id);
      setActiveTab('tasks');
    } catch (e) {
      setPreflightOk(false);
      setPreflightMessage(e instanceof Error ? e.message : '提交任务失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const fetchJobLog = async (job: DownloadJob | undefined = selectedJob) => {
    if (!job?.job_id) {
      setLogError('请先选择一个任务。');
      return;
    }
    if (!user) {
      setLogError('请先登录账号，再查看任务日志。');
      return;
    }
    setActiveTab('logs');
    setSelectedJobId(job.job_id);
    setLogLoading(true);
    setLogError('');
    try {
      const result = await api.downloadJobLog(user.user_id, job.job_id, sessionId);
      setLogData(result);
    } catch (e) {
      setLogError(e instanceof Error ? e.message : '读取任务日志失败');
      setLogData(null);
    } finally {
      setLogLoading(false);
    }
  };

  const downloadJobLog = async () => {
    if (!user || !selectedJob?.job_id) return;
    setBusyJobId(selectedJob.job_id);
    try {
      await api.downloadJobLogFile(user.user_id, selectedJob.job_id, sessionId);
    } catch (e) {
      setLogError(e instanceof Error ? e.message : '下载日志失败');
    } finally {
      setBusyJobId('');
    }
  };

  const cancelJob = async (job: DownloadJob) => {
    setBusyJobId(job.job_id);
    try {
      const result = await api.cancelDownloadJob(job.job_id, userId, '用户在控制台取消任务。', sessionId);
      setJobs(attachManagementViews([], result.management_views || []));
      setNotice(`已取消任务：${getJobName(job)}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '取消任务失败');
    } finally {
      setBusyJobId('');
    }
  };

  const retryJob = async (job: DownloadJob) => {
    setBusyJobId(job.job_id);
    try {
      const result = await api.retryDownloadJob(job.job_id, userId, sessionId);
      setJobs(attachManagementViews([], result.management_views || []));
      setNotice(result.auto_started ? '已创建重试任务并开始后台执行。' : `已创建重试任务：${result.reason || '等待处理'}`);
      if (result.management_view?.task_id) setSelectedJobId(result.management_view.task_id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '重试任务失败');
    } finally {
      setBusyJobId('');
    }
  };

  const deleteJob = async (job: DownloadJob) => {
    setBusyJobId(job.job_id);
    try {
      const result = await api.deleteDownloadJob(job.job_id, userId, sessionId);
      const nextJobs = attachManagementViews([], result.management_views || []);
      setJobs(nextJobs);
      setNotice(`已删除任务记录：${getJobName(job)}`);
      if (selectedJobId === job.job_id) setSelectedJobId(nextJobs[0]?.job_id || '');
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '删除任务失败');
    } finally {
      setBusyJobId('');
    }
  };

  const exportResults = async () => {
    setExporting(true);
    setNotice('');
    try {
      const result = await api.exportWorkspace(userId, sessionId, 'all');
      setNotice(`已打包 ${result.file_count} 个成果文件。`);
      await refresh();
      if (result.artifact_id) await api.downloadArtifactById(result.artifact_id, 'workspace-export.zip', userId, sessionId);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const downloadArtifact = async (artifactId: string, name: string) => {
    if (!artifactId) {
      setNotice('该结果缺少 artifact_id，无法通过安全下载解析器下载。');
      return;
    }
    try {
      const metadata = await api.artifactMetadata(artifactId, userId, sessionId);
      await api.downloadArtifactById(artifactId, metadata.filename || metadata.title || name || '成果文件', userId, sessionId);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '文件已清理、无访问权限或下载链接已失效。');
    }
  };

  const deleteArtifact = async (artifact: ConsoleArtifact) => {
    setNotice('');
    try {
      const result = await api.deleteWorkspaceArtifact({
        user_id: userId,
        session_id: sessionId,
        artifact_id: artifact.artifactId
      });
      setDashboard(result.dashboard);
      setNotice(`已删除结果文件：${artifact.label}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '删除结果文件失败');
    }
  };

  const downloadJobArtifact = async (job: DownloadJob) => {
    const ref = jobView(job)?.artifact_refs?.[0];
    if (ref?.artifact_id) {
      const metadata = await api.artifactMetadata(ref.artifact_id, userId, sessionId);
      await downloadArtifact(ref.artifact_id, metadata.filename || metadata.title || ref.title || getJobName(job));
      return;
    }
    setNotice('该任务没有可解析的 artifact_id，暂不能提供下载入口。');
  };

  const checkGscloudLoginHealth = async () => {
    if (!userId) {
      setGscloudLoginMessage('请先登录智能体账号，再检查地理空间数据云登录态。');
      return;
    }
    setGscloudLoginLoading(true);
    setGscloudLoginMessage('');
    try {
      const [platform, own] = await Promise.all([
        api.loginHealth(userId, 'gscloud', 'platform'),
        api.loginHealth(userId, 'gscloud', 'own')
      ]);
      const platformHealth = platform.login_health || {};
      const ownHealth = own.login_health || {};
      const platformText = platformHealth.ok ? '平台账号可用' : `平台账号不可用：${String(platformHealth.reason || platformHealth.detail || '需要重新登录')}`;
      const ownText = ownHealth.ok ? '用户自有账号可用' : `用户自有账号不可用：${String(ownHealth.reason || ownHealth.detail || '需要重新登录')}`;
      setGscloudLoginMessage(`${platformText}；${ownText}`);
    } catch (e) {
      setGscloudLoginMessage(e instanceof Error ? e.message : '检查地理空间数据云登录态失败');
    } finally {
      setGscloudLoginLoading(false);
    }
  };

  const renderJobActions = (job: DownloadJob) => {
    const active = canJob(job, 'cancel');
    const retryable = canJob(job, 'retry');
    const viewable = canJob(job, 'view_artifacts');
    const busy = busyJobId === job.job_id;
    return (
      <div className="flex flex-wrap items-center gap-2">
        {viewable && (
          <button className="console-secondary-button" onClick={() => downloadJobArtifact(job)}>
            <Download size={14} /> 下载
          </button>
        )}
        <button className="console-secondary-button" onClick={() => fetchJobLog(job)} disabled={busy}>
          <TerminalSquare size={14} /> 日志
        </button>
        {active && (
          <button className="console-secondary-button text-amber-700 dark:text-amber-200" onClick={() => cancelJob(job)} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" size={14} /> : <XCircle size={14} />} 取消
          </button>
        )}
        {retryable && (
          <button className="console-secondary-button" onClick={() => retryJob(job)} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" size={14} /> : <RotateCcw size={14} />} 重试
          </button>
        )}
        {!active && (
          <button className="console-icon-button text-rose-600 dark:text-rose-300" onClick={() => deleteJob(job)} disabled={busy} title="删除任务记录">
            {busy ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
          </button>
        )}
      </div>
    );
  };

  const renderOverview = () => (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-3xl border border-slate-200/90 bg-white/88 p-6 shadow-[0_18px_48px_rgba(15,23,42,.08)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/78">
        <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-slate-50">GIS 智能体管理后台</h1>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600 dark:text-slate-300">
              面向科研数据任务的控制台：统一完成数据下载、参数预检、后台执行、日志诊断、结果查看和成果导出。
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <button className="console-primary-button" onClick={() => setActiveTab('create')}>
                <Play size={16} /> 新建任务
              </button>
              <button className="console-secondary-button" onClick={openChatWorkspace}>
                <MessageSquare size={16} /> 打开智能助手
              </button>
              <button data-testid="open-map-workspace" className="console-secondary-button" onClick={onOpenMap}>
                <Map size={16} /> 空间视图
              </button>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200/90 bg-gradient-to-br from-slate-50 to-cyan-50/60 p-4 shadow-inner dark:border-slate-800 dark:from-slate-950 dark:to-cyan-950/20">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">当前运行状态</div>
              <StatusBadge status={dashboard?.runtime_status?.phase ? String(dashboard.runtime_status.phase) : summary.active ? 'running' : 'completed'} />
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              {String(dashboard?.runtime_status?.label || '就绪')}：{String(dashboard?.runtime_status?.detail || '等待新任务')}
            </p>
            <div className="mt-4">
              <ProgressBar value={Number(dashboard?.runtime_status?.progress || (summary.active ? 45 : 100))} tone={summary.failed ? 'failed' : summary.active ? 'running' : 'succeeded'} />
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {capabilityCards.map(({ title, description, icon: Icon }) => (
          <Panel key={title} className="p-4">
            <div className="mb-4 grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-slate-100 to-cyan-50 text-slate-700 shadow-inner dark:from-slate-800 dark:to-cyan-950/25 dark:text-slate-200">
              <Icon size={19} strokeWidth={1.7} />
            </div>
            <div className="text-sm font-bold text-slate-950 dark:text-slate-50">{title}</div>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
          </Panel>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="全部任务" value={summary.total} hint="包含下载、重试、取消和已完成任务。" icon={ClipboardList} />
        <MetricCard label="运行/等待" value={summary.active} hint={`${summary.running} 个执行中，${summary.waiting} 个等待或需处理。`} icon={Activity} />
        <MetricCard label="数据资产" value={Number(counts.table || 0) + Number(counts.vector || 0) + Number(counts.raster || 0) + Number(counts.document || 0)} hint="当前工作区可用表格、矢量、栅格和文档。" icon={Database} />
        <MetricCard label="结果文件" value={artifacts.length} hint="可下载的报告、图表、数据和压缩包。" icon={FileArchive} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_.9fr]">
        <Panel className="p-5">
          <SectionHeader title="最近任务" description="快速查看运行状态，失败任务可直接进入日志诊断。" action={<button className="console-link-button" onClick={() => setActiveTab('tasks')}>查看全部 <ChevronRight size={15} /></button>} />
          {jobs.length === 0 ? (
            <EmptyState icon={ClipboardList} title="还没有任务" description="从新建任务开始，系统会在这里展示下载、处理和导出进度。" action={<button className="console-primary-button" onClick={() => setActiveTab('create')}>新建任务</button>} />
          ) : (
            <div className="space-y-3">
              {jobs.slice(0, 4).map((job) => (
                <JobCompactRow key={job.job_id} job={job} onSelect={() => { setSelectedJobId(job.job_id); setActiveTab('tasks'); }} />
              ))}
            </div>
          )}
        </Panel>
        <Panel className="p-5">
          <SectionHeader title="最近结果" description="成功任务和工作区导出的文件会集中展示。" action={<button className="console-link-button" onClick={() => setActiveTab('results')}>结果文件 <ChevronRight size={15} /></button>} />
          {artifacts.length === 0 ? (
            <EmptyState icon={FileText} title="暂无结果文件" description="任务完成后，报告、图表、数据和打包文件会出现在这里。" />
          ) : (
            <ArtifactList artifacts={artifacts.slice(0, 5)} onDownload={downloadArtifact} onDelete={deleteArtifact} />
          )}
        </Panel>
      </div>
    </div>
  );

  const renderCreateTask = () => (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <Panel className="p-5">
        <SectionHeader title="新建数据下载任务" description="先配置参数并执行预检，确认登录态和候选数据后再启动后台任务。" />
        <div className="grid gap-4 md:grid-cols-2">
          <label className="console-field md:col-span-2">
            <span>数据产品</span>
            <select value={downloadResourceType} onChange={(event) => setDownloadResourceType(event.target.value)}>
              {downloadProducts.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="console-field">
            <span>下载区域</span>
            <input value={downloadRegion} onChange={(event) => setDownloadRegion(event.target.value)} placeholder="例如：成都市 / 四川省" />
          </label>
          <label className="console-field">
            <span>账号模式</span>
            <select value={accountMode} onChange={(event) => setAccountMode(event.target.value as 'platform' | 'own')}>
              <option value="platform">平台账号</option>
              <option value="own">用户自有账号</option>
            </select>
          </label>
          <label className="console-field">
            <span>开始日期</span>
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>
          <label className="console-field">
            <span>结束日期</span>
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>
          <label className="console-field md:col-span-2">
            <span>输出名称</span>
            <input value={outputName} onChange={(event) => setOutputName(event.target.value)} placeholder={defaultOutputName} />
          </label>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <button className="console-secondary-button justify-center" onClick={runPreflight} disabled={preflightLoading || submitLoading}>
            {preflightLoading ? <Loader2 className="animate-spin" size={16} /> : <Search size={16} />} 先预检
          </button>
          <button className="console-primary-button justify-center" onClick={submitTask} disabled={submitLoading || preflightLoading}>
            {submitLoading ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />} 启动任务
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {preflightLoading && <LoadingState label="正在检查登录态、候选数据和参数完整性" />}
          {preflightMessage && <StateMessage tone={preflightOk ? 'success' : 'error'}>{preflightMessage}</StateMessage>}
          {notice && <StateMessage tone="success">{notice}</StateMessage>}
        </div>
      </Panel>

      <Panel className="p-5">
        <SectionHeader title="任务流程" description="控制台把下载任务拆成可追踪的阶段。" />
        <ol className="space-y-3">
          {[
            ['配置参数', '选择数据产品、区域、时间和账号模式。'],
            ['执行预检', '检查登录态、额度、区域解析和候选记录。'],
            ['启动任务', '后台创建任务并进入队列或直接运行。'],
            ['查看日志', '任务失败时定位具体阶段和建议动作。'],
            ['导出结果', '成功后下载成果文件或打包整个工作区。']
          ].map(([title, desc], index) => (
            <li key={title} className="flex gap-3">
              <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-blue-600 to-cyan-500 text-xs font-bold text-white shadow-md">{index + 1}</div>
              <div>
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</div>
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );

  const renderTasks = () => (
    <div className="space-y-5">
      <Panel className="p-5">
        <SectionHeader
          title="任务中心"
          description="统一查看任务状态、阶段进度、失败原因，并执行取消、重试、删除和日志查看。"
          action={<button className="console-primary-button" onClick={() => setActiveTab('create')}><Play size={15} /> 新建任务</button>}
        />
        <div className="relative mb-4">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input className="console-search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务名称、区域、产品、状态或阶段" />
        </div>
        {filteredJobs.length === 0 ? (
          <EmptyState icon={ClipboardList} title={jobs.length ? '没有匹配的任务' : '还没有任务'} description={jobs.length ? '调整搜索条件，或清空关键字查看全部任务。' : '创建任务后，这里会展示完整生命周期和可用操作。'} />
        ) : (
          <div className="space-y-3">
            {filteredJobs.map((job) => (
              <JobDetailRow
                key={job.job_id}
                job={job}
                selected={selectedJob?.job_id === job.job_id}
                onSelect={() => setSelectedJobId(job.job_id)}
                actions={renderJobActions(job)}
              />
            ))}
          </div>
        )}
      </Panel>

      {selectedJob && (
        <Panel className="p-5">
          <SectionHeader title="任务详情" description="当前任务参数、阶段、失败信息和质量检查。" action={renderJobActions(selectedJob)} />
          <div className="grid gap-4 lg:grid-cols-3">
            <InfoItem label="任务编号" value={jobTaskId(selectedJob)} />
            <InfoItem label="数据源" value={jobSourceName(selectedJob)} />
            <InfoItem label="产品类型" value={selectedJob.resource_type || '--'} />
            <InfoItem label="区域" value={selectedJob.region || '--'} />
            <InfoItem label="可用操作" value={jobActions(selectedJob).join(' / ') || '--'} />
            <InfoItem label="更新时间" value={jobView(selectedJob)?.updated_at || selectedJob.updated_at || '--'} />
          </div>
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="font-semibold text-slate-700 dark:text-slate-200">当前阶段：{jobStage(selectedJob)}</span>
              <span className="text-slate-500 dark:text-slate-400">{formatPercent(jobProgress(selectedJob))}%</span>
            </div>
            <ProgressBar value={jobProgress(selectedJob)} tone={normalizeTaskStatus(jobStatus(selectedJob)).tone} />
          </div>
          {jobView(selectedJob)?.warnings?.length ? (
            <div className="mt-4">
              <StateMessage tone="info">
                {jobView(selectedJob)?.warnings?.join('；')}
              </StateMessage>
            </div>
          ) : null}
          {jobUserMessage(selectedJob) && (
            <div className="mt-4">
              <StateMessage tone="error">
                <b>失败诊断：</b>{jobUserMessage(selectedJob)}
              </StateMessage>
            </div>
          )}
        </Panel>
      )}
    </div>
  );

  const renderLogs = () => (
    <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
      <Panel className="p-5">
        <SectionHeader title="选择任务" description="按任务查看结构化运行日志。" />
        {jobs.length === 0 ? (
          <EmptyState icon={TerminalSquare} title="暂无可查看日志的任务" description="任务创建后，可在这里查看执行记录。" />
        ) : (
          <div className="space-y-2">
            {jobs.map((job) => (
              <button
                key={job.job_id}
                onClick={() => fetchJobLog(job)}
                className={cn('w-full rounded-2xl border p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:bg-cyan-50/60 hover:shadow-md dark:hover:border-cyan-800 dark:hover:bg-cyan-950/25', selectedJob?.job_id === job.job_id ? 'border-cyan-300 bg-cyan-50/70 ring-4 ring-cyan-100/60 dark:border-cyan-800 dark:bg-cyan-950/35 dark:ring-cyan-950/40' : 'border-slate-200/90 bg-white/86 dark:border-slate-800 dark:bg-slate-900/78')}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-semibold">{getJobName(job)}</span>
                  <StatusBadge status={jobStatus(job)} />
                </div>
                <div className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{jobStage(job)}</div>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel className="p-5">
        <SectionHeader
          title="运行日志"
          description="展示任务主状态、场景日志、分幅日志和审计事件。"
          action={<button className="console-secondary-button" disabled={!selectedJob || logLoading} onClick={() => fetchJobLog(selectedJob)}><RefreshCcw size={15} /> 刷新</button>}
        />
        {logLoading ? <LoadingState label="正在读取任务日志" /> : logError ? <StateMessage tone="error">{logError}</StateMessage> : !logData ? (
          <EmptyState icon={TerminalSquare} title="请选择任务查看日志" description="点击左侧任务后，这里会展示阶段日志和诊断信息。" />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-4">
              <InfoItem label="状态" value={normalizeTaskStatus(logData.management_view?.status || 'running').label} />
              <InfoItem label="阶段" value={logData.management_view?.action_state?.stage || '--'} />
              <InfoItem label="场景日志" value={logData.diagnostic_event_views?.scene_jobs?.length || 0} />
              <InfoItem label="审计事件" value={logData.diagnostic_event_views?.audit_events?.length || 0} />
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100 shadow-inner dark:border-slate-700">
              <div>任务编号：{logData.management_view?.task_id || '--'}</div>
              <div>任务状态：{logData.management_view?.status || '--'}</div>
              <div>执行阶段：{logData.management_view?.action_state?.stage || '--'}</div>
              <div>完成进度：{formatPercent(logData.management_view?.progress ?? 0)}%</div>
              <div>数据来源：{logData.management_view?.source_name || '--'}</div>
              {logData.management_view?.user_message && <div className="text-rose-300">提示信息：{logData.management_view.user_message}</div>}
            </div>
            <LogGroup title="场景日志" items={logData.diagnostic_event_views?.scene_jobs || []} empty="暂无场景日志" />
            <LogGroup title="分幅日志" items={logData.diagnostic_event_views?.tile_jobs || []} empty="暂无分幅日志" />
            <LogGroup title="审计事件" items={logData.diagnostic_event_views?.audit_events || []} empty="暂无审计事件" />
            <button className="console-secondary-button" onClick={downloadJobLog} disabled={!selectedJob || busyJobId === selectedJob?.job_id}>
              {busyJobId === selectedJob?.job_id ? <Loader2 className="animate-spin" size={15} /> : <Download size={15} />} 下载原始日志
            </button>
          </div>
        )}
      </Panel>
    </div>
  );

  const renderResults = () => {
    const panelFiles = resultPanel?.files?.filter((file) => file.artifact_id) || [];
    return (
      <div className="space-y-6">
        <Panel className="p-5">
          <SectionHeader
            title="结果文件"
            description="集中查看任务产出的报告、图表、数据文件和打包成果。"
            action={<button className="console-primary-button" onClick={exportResults} disabled={exporting}>{exporting ? <Loader2 className="animate-spin" size={15} /> : <FileArchive size={15} />} 打包导出</button>}
          />
          {notice && <div className="mb-4"><StateMessage tone="success">{notice}</StateMessage></div>}
          <div className="grid gap-4 md:grid-cols-3">
            <MetricCard label="可下载文件" value={artifacts.length + panelFiles.length} hint="包含工作区成果和最新智能体返回文件。" icon={FileText} />
            <MetricCard label="模型结果" value={dashboard?.model_results?.length || 0} hint="已识别的模型指标和分析产物。" icon={BarChart3} />
            <MetricCard label="最近流水线" value={dashboard?.latest_pipeline ? '已生成' : '暂无'} hint={String(dashboard?.latest_pipeline?.pipeline_name || '运行分析流程后会显示。')} icon={Activity} />
          </div>
        </Panel>

        {resultPanel?.has_results && (
          <Panel className="p-5">
            <SectionHeader title={resultPanel.title || '最新处理结果'} description="来自最近一次智能体响应的结果摘要。" />
            {resultPanel.recommendations?.length ? (
              <div className="space-y-2">
                {resultPanel.recommendations.map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded-2xl border border-blue-100 bg-blue-50/85 px-3 py-2 text-sm font-semibold leading-6 text-blue-800 shadow-sm dark:border-blue-900/55 dark:bg-blue-950/35 dark:text-blue-200">{item}</div>
                ))}
              </div>
            ) : <p className="text-sm text-slate-500 dark:text-slate-400">暂无建议。</p>}
          </Panel>
        )}

        <Panel className="p-5">
          <SectionHeader title="工作区成果" description="后端已公开下载地址的结果文件。" />
          {artifacts.length === 0 && panelFiles.length === 0 ? (
            <EmptyState icon={FileText} title="暂无结果文件" description="任务成功后，文件会自动出现在这里；也可以从任务中心打开成功任务查看下载入口。" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <ArtifactList artifacts={artifacts} onDownload={downloadArtifact} onDelete={deleteArtifact} />
              {panelFiles.length > 0 && (
                <div className="space-y-2">
                  {panelFiles.map((file) => (
                    <button key={file.artifact_id || file.label} onClick={() => downloadArtifact(file.artifact_id || '', file.label || 'result')} className="flex w-full items-center justify-between gap-3 rounded-2xl border border-slate-200/90 bg-white/86 px-4 py-3 text-left text-sm shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:bg-cyan-50/60 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/78 dark:hover:border-cyan-800 dark:hover:bg-cyan-950/25">
                      <span className="min-w-0 truncate font-semibold">{file.label || file.title || file.name || file.filename || file.artifact_id || '结果文件'}</span>
                      <Download className="shrink-0 text-slate-400" size={16} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>
    );
  };

  const renderDataAssets = () => (
    <div className="space-y-6">
      <Panel className="p-5">
        <SectionHeader title="数据资产" description="工作区数据概览和本地文件库导入入口。" />
        <div className="grid gap-4 md:grid-cols-4">
          <MetricCard label="表格" value={counts.table || 0} hint="CSV、Excel 和指标表。" icon={FileText} />
          <MetricCard label="矢量" value={counts.vector || 0} hint="边界、站点、GeoJSON 等。" icon={Layers3} />
          <MetricCard label="栅格" value={counts.raster || 0} hint="DEM、遥感影像和专题栅格。" icon={Map} />
          <MetricCard label="文档" value={counts.document || 0} hint="说明、报告和 Markdown。" icon={Archive} />
        </div>
      </Panel>
      <LocalLibraryPanel userId={userId} sessionId={sessionId || chatContext?.session_id} onImported={refresh} />
    </div>
  );

  const renderSettings = () => (
    <Panel className="p-5">
      <SectionHeader title="设置与运行环境" description="当前保留原有设置能力，这里补充后台化的信息入口。" />
      <div className="grid gap-4 md:grid-cols-2">
        <InfoItem label="账号状态" value={user ? user.email : '未登录'} />
        <InfoItem label="当前套餐" value={user?.plan || '--'} />
        <InfoItem label="平台额度" value={user ? `${Number(user.platform_monthly_used || 0)} / ${Number(user.platform_monthly_quota || 0)}` : '--'} />
        <InfoItem label="工作区" value={workspaceDisplayName} />
      </div>
      <div className="mt-5 flex flex-wrap gap-3">
        <button data-testid="open-map-workspace" className="console-secondary-button" onClick={onOpenMap}><Map size={15} /> 打开原地图工作台</button>
        <button className="console-secondary-button" onClick={openChatWorkspace}><Bot size={15} /> 打开智能助手</button>
      </div>
    </Panel>
  );

  const renderSettingsV2 = () => (
    <div className="space-y-5">
      <Panel className="p-5">
        <SectionHeader title="设置与运行环境" description="当前保留原有设置能力，这里补充后台化的信息入口。" />
        <div className="grid gap-4 md:grid-cols-2">
          <InfoItem label="账号状态" value={user ? user.email : '未登录'} />
          <InfoItem label="当前套餐" value={user?.plan || '--'} />
          <InfoItem label="平台额度" value={user ? `${Number(user.platform_monthly_used || 0)} / ${Number(user.platform_monthly_quota || 0)}` : '--'} />
          <InfoItem label="工作区" value={workspaceDisplayName} />
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button data-testid="open-map-workspace" className="console-secondary-button" onClick={onOpenMap}><Map size={15} /> 打开原地图工作台</button>
          <button className="console-secondary-button" onClick={openChatWorkspace}><Bot size={15} /> 打开智能助手</button>
        </div>
      </Panel>

      <Panel className="p-5">
        <SectionHeader title="地理空间数据云登录" description="检查平台账号和用户自有账号的登录态；需要重新登录时请回到地图工作台打开下载工具。" />
        <GSCloudAccountPanel enabled={Boolean(user)} />
        <div className="grid gap-4 md:grid-cols-2">
          <InfoItem label="平台账号模式" value="由后台账号池提供，按套餐额度使用。" />
          <InfoItem label="用户自有账号模式" value="使用当前用户保存的 GSCloud 登录态，不占用平台额度。" />
        </div>
        {gscloudLoginMessage && <div className="mt-4"><StateMessage tone={gscloudLoginMessage.includes('不可用') || gscloudLoginMessage.includes('失败') ? 'error' : 'success'}>{gscloudLoginMessage}</StateMessage></div>}
        <div className="mt-5 flex flex-wrap gap-3">
          <button className="console-secondary-button" onClick={checkGscloudLoginHealth} disabled={gscloudLoginLoading}>
            {gscloudLoginLoading ? <Loader2 className="animate-spin" size={15} /> : <ShieldCheck size={15} />} 检查 GSCloud 登录态
          </button>
          <button data-testid="open-map-workspace" className="console-primary-button" onClick={onOpenMap}><Map size={15} /> 打开地图工作台登录入口</button>
        </div>
      </Panel>

      <Panel className="p-5">
        <SectionHeader title="知识与能力管理" description="上传知识库文档，完成检索测试后提交审核并激活。" />
        <CapabilityManagementPanel />
      </Panel>
    </div>
  );

  const renderChat = () => (
    <ChatWorkspace
      mode="page"
      user={user}
      setUser={setUser}
      onMapTextCommand={onMapTextCommand}
      externalPrompt={externalPrompt}
      onResultPanel={onResultPanel}
      onSessionChange={onSessionChange}
      chatContext={chatContext}
      mentionDatasets={dashboard?.datasets || []}
    />
  );

  const renderContent = () => {
    if (activeTab === 'chat') return renderChat();
    if (loading) return <LoadingState label="正在加载控制台数据" />;
    const content =
      activeTab === 'overview' ? renderOverview()
      : activeTab === 'create' ? renderCreateTask()
      : activeTab === 'tasks' ? renderTasks()
      : activeTab === 'logs' ? renderLogs()
      : activeTab === 'results' ? renderResults()
      : activeTab === 'data' ? renderDataAssets()
      : renderSettingsV2();
    return (
      <div className="space-y-4">
        {error && <StateMessage tone="error">{error}</StateMessage>}
        {content}
      </div>
    );
  };

  const activateNavItem = (item: ConsoleNavItem) => {
    if (item.action === 'openMap') {
      onOpenMap?.();
      return;
    }
    setActiveTab(item.id as ConsoleTab);
  };

  return (
    <div className="no-drag fixed inset-0 z-20 flex bg-[radial-gradient(circle_at_18%_10%,rgba(8,199,232,.16),transparent_24%),linear-gradient(135deg,#f8fbff_0%,#eef5fb_52%,#eaf3ff_100%)] text-slate-950 dark:bg-[radial-gradient(circle_at_18%_10%,rgba(8,199,232,.11),transparent_26%),linear-gradient(135deg,#020617_0%,#0f172a_58%,#111827_100%)] dark:text-slate-50">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200/80 bg-white/82 px-4 py-5 shadow-[12px_0_40px_rgba(15,23,42,.05)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/70 lg:block">
        <div className="mb-7 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-cyan-500 text-white shadow-[0_14px_30px_rgba(15,98,254,.26)]">
            <Bot size={20} strokeWidth={1.7} />
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight">GIS 智能体</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">科研任务控制台</div>
          </div>
        </div>
        <nav className="space-y-1">
          {navItems.map((item) => {
            const { id, label, icon: Icon } = item;
            return (
            <button
              key={id}
              onClick={() => activateNavItem(item)}
              className={cn('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-bold transition', activeTab === id ? 'bg-gradient-to-r from-blue-600 to-cyan-600 text-white shadow-[0_12px_28px_rgba(15,98,254,.22)]' : 'text-slate-600 hover:bg-white/80 hover:text-slate-950 hover:shadow-sm dark:text-slate-300 dark:hover:bg-slate-800/70 dark:hover:text-white')}
            >
              <Icon size={17} strokeWidth={1.7} />
              {label}
            </button>
            );
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-slate-200/80 bg-white/78 px-4 py-3 shadow-[0_12px_36px_rgba(15,23,42,.04)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/72 sm:px-6">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
                <ShieldCheck size={14} /> 后端接口保持不变 · 任务驱动后台
              </div>
              <h1 className="mt-1 truncate text-lg font-bold tracking-tight text-slate-950 dark:text-slate-50">{navItems.find((item) => item.id === activeTab)?.label || '控制台'}</h1>
            </div>
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
              <button className="console-secondary-button" onClick={refresh} disabled={loading}>
                <RefreshCcw size={15} className={loading ? 'animate-spin' : ''} /> 刷新
              </button>
              <button className="console-secondary-button" onClick={openChatWorkspace}>
                <MessageSquare size={15} /> 智能助手
              </button>
              <div className="min-w-0 sm:w-[360px]">
                <AuthPanel user={user} setUser={setUser} />
              </div>
            </div>
          </div>
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1 lg:hidden">
            {navItems.map((item) => {
              const { id, label, icon: Icon } = item;
              return (
              <button
                key={id}
                onClick={() => activateNavItem(item)}
                className={cn('inline-flex shrink-0 items-center gap-2 rounded-xl border px-3 py-2 text-xs font-bold shadow-sm transition', activeTab === id ? 'border-blue-600 bg-gradient-to-r from-blue-600 to-cyan-600 text-white' : 'border-slate-200 bg-white/82 text-slate-600 hover:border-cyan-300 hover:bg-cyan-50/70 dark:border-slate-800 dark:bg-slate-900/78 dark:text-slate-300')}
              >
                <Icon size={14} /> {label}
              </button>
              );
            })}
          </div>
        </header>

        <main className={cn('min-h-0 flex-1', activeTab === 'chat' ? 'overflow-hidden p-0' : 'overflow-y-auto p-4 sm:p-6')}>
          {renderContent()}
        </main>
      </div>
    </div>
  );
}

function JobCompactRow({ job, onSelect }: { job: DownloadJob; onSelect: () => void }) {
  const status = normalizeTaskStatus(jobStatus(job));
  return (
    <button onClick={onSelect} className="w-full rounded-2xl border border-slate-200/90 bg-white/86 p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:bg-cyan-50/60 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/78 dark:hover:border-cyan-800 dark:hover:bg-cyan-950/25">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{getJobName(job)}</div>
          <div className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{jobStage(job)}</div>
        </div>
        <StatusBadge status={jobStatus(job)} />
      </div>
      <div className="mt-3">
        <ProgressBar value={jobProgress(job)} tone={status.tone} />
      </div>
    </button>
  );
}

function JobDetailRow({ job, selected, onSelect, actions }: { job: DownloadJob; selected: boolean; onSelect: () => void; actions: ReactNode }) {
  const status = normalizeTaskStatus(jobStatus(job));
  return (
    <div className={cn('rounded-2xl border bg-white/86 p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:bg-slate-900/78', selected ? 'border-cyan-300 ring-4 ring-cyan-100/80 dark:border-cyan-800 dark:ring-cyan-950/45' : 'border-slate-200/90 dark:border-slate-800')}>
      <div className="grid gap-4 xl:grid-cols-[1fr_220px_auto] xl:items-center">
        <button onClick={onSelect} className="min-w-0 text-left">
          <div className="flex flex-wrap items-center gap-2">
            <div className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{getJobName(job)}</div>
            <StatusBadge status={jobStatus(job)} />
          </div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{jobTaskId(job)}</div>
          <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            {jobSourceName(job)} · {jobStage(job)}
          </div>
        </button>
        <div>
          <div className="mb-2 flex justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>{status.description}</span>
            <span>{formatPercent(jobProgress(job))}%</span>
          </div>
          <ProgressBar value={jobProgress(job)} tone={status.tone} />
        </div>
        <div>{actions}</div>
      </div>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200/90 bg-slate-50/84 px-3 py-2 shadow-inner dark:border-slate-800 dark:bg-slate-950/78">
      <div className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</div>
      <div className="mt-1 min-w-0 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">{value}</div>
    </div>
  );
}

function ArtifactList({ artifacts, onDownload, onDelete }: { artifacts: ConsoleArtifact[]; onDownload: (artifactId: string, name: string) => void; onDelete: (artifact: ConsoleArtifact) => void }) {
  return (
    <div className="space-y-2">
      {artifacts.map((artifact) => {
        const Icon = artifactIcon(artifact.kind);
        return (
          <div key={artifact.artifactId} className="flex w-full items-center justify-between gap-3 rounded-2xl border border-slate-200/90 bg-white/86 px-4 py-3 text-left text-sm shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:bg-cyan-50/60 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/78 dark:hover:border-cyan-800 dark:hover:bg-cyan-950/25">
            <span className="flex min-w-0 items-center gap-3">
              {artifact.kind === 'visual' && artifact.previewUrl ? (
                <img data-testid="console-artifact-image-preview" src={artifact.previewUrl} alt={artifact.label} loading="lazy" className="h-12 w-16 shrink-0 rounded-lg border border-slate-200 bg-slate-50 object-cover dark:border-slate-800 dark:bg-slate-950" />
              ) : (
                <Icon className="shrink-0 text-slate-400" size={17} />
              )}
              <span className="min-w-0 truncate font-semibold">{artifact.label}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <button type="button" onClick={() => onDownload(artifact.artifactId, artifact.label)} className="console-icon-button" title="下载结果文件">
                <Download className="shrink-0 text-slate-400" size={16} />
              </button>
              <button type="button" onClick={() => onDelete(artifact)} className="console-icon-button text-rose-600 dark:text-rose-300" title="删除结果文件">
                <Trash2 size={16} />
              </button>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function LogGroup({ title, items, empty }: { title: string; items: DiagnosticEventView[]; empty: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white/86 p-4 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-900/78">
      <div className="mb-3 text-sm font-bold text-slate-900 dark:text-slate-100">{title}</div>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>
      ) : (
        <div className="space-y-2">
          {items.slice(0, 12).map((item, index) => (
            <div key={`${item.timestamp || ''}-${item.phase || ''}-${index}`} className="rounded-xl border border-slate-200/70 bg-slate-50/86 px-3 py-2 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/78 dark:text-slate-300">
              <span className="mr-3"><b>时间</b>: {item.timestamp || '--'}</span>
              <span className="mr-3"><b>阶段</b>: {item.phase || '--'}</span>
              <span className="mr-3"><b>级别</b>: {item.level || '信息'}</span>
              <span className="mr-3"><b>摘要</b>: {item.summary || '--'}</span>
              {item.error_code ? <span className="mr-3"><b>错误码</b>: {item.error_code}</span> : null}
              {item.next_action ? <span className="mr-3"><b>下一步</b>: {item.next_action}</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
