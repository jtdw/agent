import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  BookOpen,
  Box,
  CheckCircle2,
  ChevronDown,
  Circle,
  ClipboardCheck,
  Clock3,
  Copy,
  CreditCard,
  Database,
  Download,
  Eye,
  FileText,
  Gem,
  HelpCircle,
  Home,
  Layers,
  LineChart,
  Lock,
  LogIn,
  LogOut,
  Map,
  MapPin,
  MessageCircle,
  Mic,
  MoreHorizontal,
  MoreVertical,
  MousePointer2,
  Plus,
  RefreshCw,
  Ruler,
  Search,
  Send,
  Settings,
  Shield,
  Square,
  Upload,
  UserPlus,
  UserRound,
  Wrench,
  X,
  Zap,
  ZoomIn,
  ZoomOut
} from 'lucide-react';
import {
  api,
  type ChatMessage,
  type ChatSession,
  type CommercialUser,
  type DownloadJob,
  type RealtimeChatEvent,
  type ResultMapLayer,
  type ResultPanel,
  type WorkspaceArtifact,
  type WorkspaceDashboard
} from './lib/api';
import { clearStoredAuth, readStoredUser, writeStoredUser } from './lib/authStorage';
import { mergeChatContext, type ChatContextPayload } from './lib/chatContext';
import {
  mergeResultLayerState,
  resultLayerKey,
  type LayerVisibility,
  type ResultLayerPalettePreferences,
  type ResultLayerStateMap
} from './components/mapLayerPolicy';
import type { MapCommand } from './components/mapCommands';
import { MapStage } from './components/MapStage';
import './components/pixelReplica.css';

type ViewMode = 'workbench' | 'admin';
type ProfileView = 'account' | 'upgrade';
type InteractionMode = 'chat_only' | 'tool_enabled';
type LoginMode = 'login' | 'register';
type RailPanel = 'workspace' | 'layers' | 'data' | 'map' | 'observability' | 'tools' | 'history';
type StatusTone = 'success' | 'info' | 'warning' | 'danger' | 'muted';
type DatasetView = { id: string; name: string; meta: string; typeLabel: string; size: string; tone: string; crs: string; rows?: string };
type ArtifactView = { id: string; title: string; type: string; meta: string; preview: string; artifactId?: string; downloadUrl?: string };
type PipelineStep = { icon: typeof Database; title: string; detail: string; ok: boolean };
type ArtifactSource = WorkspaceArtifact | NonNullable<ResultPanel['files']>[number];
type AdminExposure = {
  schema_version?: string;
  checked_at?: string;
  environment?: string;
  requested_percent?: number;
  rollback_requested?: boolean;
  eligible_for_user_exposure?: boolean;
  recommendation?: string;
  reasons?: string[];
  blocking_reasons_human?: string[];
  deterministic_smoke?: Record<string, unknown>;
  soil_moisture_gcp_smoke?: Record<string, unknown>;
  llm_smoke?: Record<string, unknown>;
  required_reports?: Record<string, unknown>;
  next_actions?: string[];
  [key: string]: unknown;
};

const API_BASE = import.meta.env.VITE_API_BASE || '';
const EMPTY_LAYER_VISIBILITY: LayerVisibility = { dem: true, boundary: true, stations: true, soil: true };
const CAPABILITY_ITEMS = ['LCEL 编排链', 'RAG 检索', '智能体', '工具适配', '会话记忆'];
const INTERACTION_MODE_COPY: Record<InteractionMode, { label: string; detail: string; planTitle: string; steps: string[] }> = {
  chat_only: {
    label: '聊天',
    detail: '只组织回答与检索上下文，不主动执行 GIS 工具。',
    planTitle: '回答状态',
    steps: ['理解问题', '读取上下文', '检索知识', '组织回答']
  },
  tool_enabled: {
    label: '执行',
    detail: '允许经计划、校验和权限检查后执行 GIS 工具。',
    planTitle: '实时计划',
    steps: ['解析意图', '检查数据', '选择工作流', '执行工具', '生成产物']
  }
};
const RAIL_PANEL_COPY: Record<RailPanel, { title: string; subtitle: string; search: string; tabs: [string, string]; hintTitle: string; hintDetail: string; actions: string[] }> = {
  workspace: {
    title: '工作台总览',
    subtitle: '数据、图层、会话与 RAG 状态',
    search: '搜索数据集、图层或会话...',
    tabs: ['数据集', '图层'],
    hintTitle: '总览面板',
    hintDetail: '保留旧版工作台的上传、图层、坐标系和会话入口，适合快速确认当前 GIS 工作流状态。',
    actions: ['上传数据', '刷新会话', '查看知识命中']
  },
  layers: {
    title: '图层控制',
    subtitle: '地图图层、透明度与显示状态',
    search: '搜索图层名称或类型...',
    tabs: ['可见图层', '样式'],
    hintTitle: '图层面板',
    hintDetail: '点击后聚焦地图图层列表，适合检查矢量、栅格、结果图层是否已绑定会话。',
    actions: ['开关图层', '检查透明度', '同步地图']
  },
  data: {
    title: '数据资产',
    subtitle: '上传文件、产物与坐标信息',
    search: '搜索文件名、CRS 或数据类型...',
    tabs: ['上传数据', '产物'],
    hintTitle: '数据面板',
    hintDetail: '聚焦文件资产，延续旧版工作台的数据列表与坐标系检查入口。',
    actions: ['上传 Shapefile', '查看 CRS', '下载产物']
  },
  map: {
    title: '地图视图',
    subtitle: '空间范围、选择与制图结果',
    search: '搜索地点、图层或地图命令...',
    tabs: ['地图工具', '范围'],
    hintTitle: '地图面板',
    hintDetail: '用于提示用户可在地图上选择范围、量测、检查结果图层和地图预览。',
    actions: ['选择范围', '量测距离', '打开图例']
  },
  observability: {
    title: '观测窗口',
    subtitle: '暴露、门禁、错误率与延迟',
    search: '搜索门禁、指标或证据文件...',
    tabs: ['运行指标', '门禁'],
    hintTitle: '观测面板',
    hintDetail: '聚焦 runtime exposure、staging gate、artifact/map 输出与 latency 指标。',
    actions: ['查看暴露', '检查门禁', '打开管理']
  },
  tools: {
    title: '工具编排',
    subtitle: 'GIS 工作流、Chain 与工具适配',
    search: '搜索工具、工作流或任务类型...',
    tabs: ['工作流', '工具'],
    hintTitle: '工具面板',
    hintDetail: '用于提醒用户切换到执行模式后，智能体会按计划调用稳定 GIS 工作流。',
    actions: ['裁剪矢量', '表格转点', '栅格预测']
  },
  history: {
    title: '历史记录',
    subtitle: '会话消息、任务与产物轨迹',
    search: '搜索历史消息、任务或产物...',
    tabs: ['会话', '任务'],
    hintTitle: '历史面板',
    hintDetail: '保留旧版工作台“任务轨迹”的思想，用于追踪会话、任务、下载和结果摘要。',
    actions: ['查看消息', '检查任务', '复用产物']
  }
};

const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  available: '可用',
  blocked: '阻断',
  canceled: '已取消',
  completed: '已完成',
  done: '完成',
  error: '错误',
  failed: '失败',
  free: '免费版',
  local: '本地',
  missing: '缺失',
  not_required: '非必需',
  observe: '观察中',
  observe_only: '仅观察',
  ok: '正常',
  passed: '通过',
  pending: '待处理',
  production: '生产',
  queued: '排队中',
  required: '必需',
  rollback: '回滚',
  running: '运行中',
  staging: '预发',
  succeeded: '成功',
  success: '成功',
  waiting: '等待中',
  waiting_login: '等待登录',
  waiting_manual: '等待人工处理'
};

const DATASET_TYPE_LABELS: Record<string, string> = {
  boundary: '边界',
  csv: '表格',
  dataset: '数据集',
  artifact: '产物',
  gate: '门禁',
  feature: '要素',
  geojson: '矢量',
  heat: '热力图',
  json: 'JSON',
  line: '线要素',
  map: '地图',
  point: '点要素',
  points: '点要素',
  polygon: '面要素',
  raster: '栅格',
  report: '报告',
  shp: '矢量',
  summary: '摘要',
  table: '表格',
  vector: '矢量'
};

function labelFromMap(value: unknown, labels: Record<string, string>, fallback = '--') {
  const text = String(value ?? '').trim();
  if (!text) return fallback;
  const normalized = text.toLowerCase().replace(/\s+/g, '_');
  return labels[normalized] || labels[text.toLowerCase()] || text;
}

function statusLabel(value: unknown, fallback = '--') {
  return labelFromMap(value, STATUS_LABELS, fallback);
}

function datasetTypeLabel(value: unknown) {
  return labelFromMap(value, DATASET_TYPE_LABELS, '数据集');
}

function planLabel(value: unknown) {
  return labelFromMap(value, { ...STATUS_LABELS, pro: '专业版', enterprise: '企业版' }, '免费版');
}

function StatusChip({ children, tone = 'muted' }: { children: ReactNode; tone?: StatusTone }) {
  return (
    <span className={`pxr-chip pxr-chip-${tone}`}>
      <span className="pxr-chip-dot" />
      {children}
    </span>
  );
}

function IconButton({ children, title, onClick }: { children: ReactNode; title: string; onClick?: () => void }) {
  return (
    <button className="pxr-icon-button" title={title} type="button" onClick={onClick}>
      {children}
    </button>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function firstText(record: Record<string, unknown>, keys: string[], fallback = '') {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return fallback;
}

function numberValue(value: unknown, fallback = 0) {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function formatBytes(value: unknown) {
  const bytes = numberValue(value, 0);
  if (!bytes) return '--';
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function shortTime(value: unknown) {
  if (!value) return '--';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function dateTime(value: unknown) {
  if (!value) return '--';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function compactText(value = '', length = 140) {
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length - 1)}...` : text;
}

function statusTone(status: unknown): StatusTone {
  const text = String(status || '').toLowerCase();
  if (['completed', 'succeeded', 'success', 'passed', 'available', 'ok', 'done'].some((item) => text.includes(item))) return 'success';
  if (['failed', 'error', 'blocked', 'missing', 'rollback'].some((item) => text.includes(item))) return 'danger';
  if (['running', 'queued', 'waiting', 'pending'].some((item) => text.includes(item))) return 'warning';
  if (text) return 'info';
  return 'muted';
}

function datasetTone(name: string, type: string) {
  const text = `${name} ${type}`.toLowerCase();
  if (text.includes('tif') || text.includes('raster')) return 'blue';
  if (text.includes('csv') || text.includes('table')) return 'green';
  if (text.includes('point')) return 'green';
  return 'purple';
}

function datasetViews(dashboard: WorkspaceDashboard | null): DatasetView[] {
  return (dashboard?.datasets || []).map((item, index) => {
    const record = asRecord(item);
    const name = firstText(record, ['name', 'dataset_name', 'filename', 'title', 'path'], `数据集_${index + 1}`);
    const rawTypeLabel = firstText(record, ['type', 'kind', 'data_type', 'geometry_type'], '数据集');
    const typeLabel = datasetTypeLabel(rawTypeLabel);
    const crs = firstText(record, ['crs', 'epsg', 'srs'], 'CRS --');
    const rows = firstText(record, ['row_count', 'rows', 'feature_count', 'count']);
    const size = formatBytes(record.size_bytes || record.size || record.bytes);
    const metaParts = [typeLabel, rows ? `${rows} 条记录` : '', crs].filter(Boolean);
    return {
      id: firstText(record, ['id', 'dataset_id', 'path'], `${name}-${index}`),
      name,
      meta: metaParts.join(' · ') || '数据集',
      typeLabel,
      size,
      crs,
      rows,
      tone: datasetTone(name, rawTypeLabel)
    };
  });
}

function artifactTitle(item: ArtifactSource, index: number) {
  const record = asRecord(item);
  return item.title || item.name || item.filename || firstText(record, ['label']) || item.path?.split(/[\\/]/).pop() || `产物_${index + 1}`;
}

function artifactKind(title: string, rawType = '') {
  const text = `${title} ${rawType}`.toLowerCase();
  if (text.includes('png') || text.includes('jpg') || text.includes('jpeg') || text.includes('map')) return 'map';
  if (text.includes('tif') || text.includes('raster')) return 'heat';
  if (text.includes('json') || text.includes('report') || text.includes('summary')) return 'json';
  if (text.includes('gate') || text.includes('quality')) return 'gate';
  if (text.includes('point') || text.includes('csv')) return 'points';
  return 'boundary';
}

function artifactViews(dashboard: WorkspaceDashboard | null, resultPanel: ResultPanel | null): ArtifactView[] {
  const dashboardArtifacts = dashboard?.artifacts || [];
  const panelFiles = resultPanel?.files || [];
  const merged = [...dashboardArtifacts, ...panelFiles];
  const seen = new Set<string>();
  return merged
    .map((item, index) => {
      const record = asRecord(item);
      const title = artifactTitle(item, index);
      const rawType = firstText(record, ['type', 'kind'], '产物');
      const key = item.artifact_id || item.path || item.download_url || `${title}-${index}`;
      return {
        id: key,
        title,
        type: datasetTypeLabel(rawType),
        meta: formatBytes((item as WorkspaceArtifact).size),
        preview: artifactKind(title, rawType),
        artifactId: item.artifact_id,
        downloadUrl: item.download_url
      };
    })
    .filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
}

function latestAssistantSummary(messages: ChatMessage[], dashboard: WorkspaceDashboard | null) {
  const assistant = [...messages].reverse().find((message) => message.role === 'assistant' && message.content.trim());
  return assistant?.content || dashboard?.summary || '';
}

function capabilityKnowledge(dashboard: WorkspaceDashboard | null) {
  const groups = dashboard?.capability_groups || {};
  const items = Object.values(groups).flat().filter(Boolean);
  return items.slice(0, 3);
}

function buildPipeline(dashboard: WorkspaceDashboard | null, jobs: DownloadJob[], layers: ResultMapLayer[], exposure: AdminExposure | null): PipelineStep[] {
  const datasets = dashboard?.datasets?.length || 0;
  const artifacts = dashboard?.artifacts?.length || 0;
  const activities = dashboard?.activity?.length || 0;
  const running = jobs.filter((job) => ['running', 'queued', 'waiting_login', 'waiting_manual'].includes(String(job.status || job.state || '').toLowerCase())).length;
  const completed = jobs.filter((job) => ['completed', 'succeeded'].includes(String(job.status || job.state || '').toLowerCase())).length;
  return [
    { icon: Database, title: '数据识别', detail: datasets ? `${datasets} 个数据集` : '等待上传', ok: datasets > 0 },
    { icon: Shield, title: '验证', detail: activities ? `${activities} 条活动` : '等待执行', ok: activities > 0 },
    { icon: ClipboardCheck, title: '计划', detail: dashboard?.latest_pipeline ? '计划已生成' : '等待任务', ok: Boolean(dashboard?.latest_pipeline) },
    { icon: Wrench, title: '工具', detail: running ? `${running} 个运行中` : completed ? `${completed} 个完成` : '暂无任务', ok: completed > 0 && running === 0 },
    { icon: MapPin, title: '地图', detail: layers.length ? `${layers.length} 个图层` : '暂无图层', ok: layers.length > 0 },
    { icon: Box, title: '产物', detail: artifacts ? `${artifacts} 个产物` : '暂无产物', ok: artifacts > 0 },
    { icon: CheckCircle2, title: '质量门禁', detail: exposure?.eligible_for_user_exposure ? '门禁通过' : '只读观察', ok: Boolean(exposure?.eligible_for_user_exposure) }
  ];
}

function buildWorkflowRows(dashboard: WorkspaceDashboard | null, jobs: DownloadJob[]) {
  const activityRows = (dashboard?.activity || []).slice(-6).map((item, index) => {
    const record = asRecord(item);
    return {
      title: firstText(record, ['title', 'event', 'type', 'name'], `活动 ${index + 1}`),
      detail: firstText(record, ['detail', 'message', 'summary', 'description'], '工作区活动'),
      time: shortTime(record.created_at || record.updated_at || record.time),
      state: firstText(record, ['status', 'state'], '记录')
    };
  });
  const jobRows = jobs.slice(0, 6).map((job) => ({
    title: job.output_name || job.resource_type || job.source_key || job.job_id,
    detail: job.message || job.stage || job.status_label || job.job_id,
    time: job.updated_at ? shortTime(job.updated_at) : `${Math.round(numberValue(job.progress, 0))}%`,
    state: job.status || job.state || '任务'
  }));
  return [...activityRows, ...jobRows].slice(0, 8);
}

function buildGateRows(exposure: AdminExposure | null) {
  if (!exposure) return [];
  const deterministic = asRecord(exposure.deterministic_smoke);
  const soil = asRecord(exposure.soil_moisture_gcp_smoke);
  const llm = asRecord(exposure.llm_smoke);
  return [
    ['预发观测窗口门禁', '暴露', '只读检查', exposure.eligible_for_user_exposure ? '通过' : '阻断', statusLabel(exposure.recommendation), exposure.checked_at || '--'],
    ['确定性主动冒烟', '冒烟', '部署后', statusLabel(firstText(deterministic, ['status'], deterministic.ok === false ? '失败' : '通过')), firstText(deterministic, ['latest_report', 'report_path'], '--'), exposure.checked_at || '--'],
    ['土壤水分 / GCP 周期门禁', '观测', '周期', statusLabel(firstText(soil, ['status'], soil.ok === false ? '失败' : '通过')), firstText(soil, ['latest_report', 'report_path'], '--'), exposure.checked_at || '--'],
    ['LLM 冒烟', '可选', llm.required ? '必需' : '非必需', statusLabel(firstText(llm, ['status'], 'not_required')), firstText(llm, ['latest_report'], '--'), exposure.checked_at || '--']
  ];
}

function resolveInteractionMode(sessions: ChatSession[] | undefined, sessionId: string): InteractionMode {
  const current = sessions?.find((session) => session.session_id === sessionId) || sessions?.[0];
  return current?.interaction_mode === 'tool_enabled' ? 'tool_enabled' : 'chat_only';
}

async function fetchAdminExposure(): Promise<AdminExposure> {
  const response = await fetch(`${API_BASE}/api/admin/agent-runtime/exposure`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<AdminExposure>;
}

function WorkbenchTopBar({
  onAdmin,
  onLogin,
  onLogout,
  exposure,
  dashboard,
  user
}: {
  onAdmin: () => void;
  onLogin: () => void;
  onLogout: () => void;
  exposure: AdminExposure | null;
  dashboard: WorkspaceDashboard | null;
  user: CommercialUser | null;
}) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileView, setProfileView] = useState<ProfileView>('account');
  const runtime = dashboard?.runtime_status || {};
  const environment = statusLabel(exposure?.environment || firstText(runtime, ['environment'], 'local'));
  const percent = exposure?.requested_percent ?? numberValue(runtime.exposure_percent, 0);
  const latency = firstText(runtime, ['latency_p95_ms', 'p95_ms'], '--');
  const initials = '我';
  const datasetCount = dashboard?.datasets?.length || 0;
  const artifactCount = dashboard?.artifacts?.length || 0;
  const plan = planLabel(user?.plan);
  const quota = numberValue(user?.platform_monthly_quota, 100);
  const used = numberValue(user?.platform_monthly_used, user ? 18 : 0);
  const quotaPercent = quota ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  const quotaTone = quotaPercent >= 80 ? 'is-high' : quotaPercent >= 45 ? 'is-mid' : 'is-low';
  const openAdminFromProfile = () => {
    setProfileOpen(false);
    onAdmin();
  };
  const handleLogout = () => {
    setProfileOpen(false);
    onLogout();
  };
  const toggleProfile = () => {
    if (!user) {
      onLogin();
      return;
    }
    setProfileOpen((open) => {
      const next = !open;
      if (next) setProfileView('account');
      return next;
    });
  };
  useEffect(() => {
    if (!user) setProfileOpen(false);
  }, [user]);
  return (
    <header className="pxr-workbench-header">
      <div className="pxr-brand">GIS 智能工作台</div>
      <button className="pxr-project-select" type="button">
        {dashboard?.current_session_id || '当前工作区'} <ChevronDown size={14} />
      </button>
      <div className="pxr-status-strip">
        <span>环境：</span><strong>{environment}</strong><Circle size={7} className="pxr-dot-blue" />
        <span className="pxr-divider" />
        <span>暴露比例：</span><strong>{percent}%</strong><Circle size={7} className={exposure?.eligible_for_user_exposure ? 'pxr-dot-green' : 'pxr-dot-amber'} />
        <span className="pxr-divider" />
        <span>{exposure?.eligible_for_user_exposure ? '门禁通过' : '仅观察'}</span><CheckCircle2 size={13} className={exposure?.eligible_for_user_exposure ? 'pxr-text-green' : 'pxr-muted-text'} />
        <span className="pxr-divider" />
        <span className={exposure?.rollback_requested ? 'pxr-text-red' : 'pxr-muted-text'}>{exposure?.rollback_requested ? '回滚已开启' : '回滚未开启'}</span><Circle size={7} className={exposure?.rollback_requested ? 'pxr-dot-red' : 'pxr-dot-green'} />
        <span className="pxr-divider" />
        <span>会话：</span><strong className="pxr-muted-text">{dashboard?.current_session_id || '--'}</strong>
        <span className="pxr-divider" />
        <span>延迟 P95:</span><strong className="pxr-muted-text">{latency}{latency !== '--' ? 'ms' : ''}</strong>
        <span className="pxr-divider" />
        <span>用户:</span><strong className="pxr-muted-text">{user?.email || '未登录'}</strong>
      </div>
      <div className="pxr-header-actions">
        <IconButton title="通知"><Bell size={17} /></IconButton>
        <IconButton title="帮助"><HelpCircle size={17} /></IconButton>
        <button className="pxr-admin-shortcut" type="button" onClick={onAdmin}>管理</button>
        {user ? (
          <div className="pxr-profile-menu-wrap">
            <button className="pxr-avatar" type="button" aria-expanded={profileOpen} aria-haspopup="menu" aria-label="打开账号菜单" onClick={toggleProfile}>
              {initials}
            </button>
            {profileOpen && (
            <section className={`pxr-profile-menu pxr-profile-menu-${profileView}`} role="menu">
              <header>
                <span className="pxr-profile-avatar">{initials}</span>
                <div>
                  <strong>{user.email}</strong>
                  <small>{profileView === 'upgrade' ? '升级后增加并发、额度和远端观测能力' : '已绑定当前工作区'}</small>
                </div>
                <button className="pxr-profile-close" type="button" aria-label="关闭账号菜单" onClick={() => setProfileOpen(false)}><X size={14} /></button>
              </header>
              <div className="pxr-profile-tabs" role="tablist" aria-label="账号中心">
                <button className={profileView === 'account' ? 'is-active' : ''} type="button" role="tab" aria-selected={profileView === 'account'} onClick={() => setProfileView('account')}><UserRound size={14} />账号</button>
                <button className={profileView === 'upgrade' ? 'is-active' : ''} type="button" role="tab" aria-selected={profileView === 'upgrade'} onClick={() => setProfileView('upgrade')}><Gem size={14} />升级</button>
              </div>

              {profileView === 'account' && (
                <>
                  <div className="pxr-profile-usage">
                    <p><Database size={14} /><span>数据集</span><b>{datasetCount}</b></p>
                    <p><Box size={14} /><span>产物</span><b>{artifactCount}</b></p>
                    <p><CreditCard size={14} /><span>当前套餐</span><b>{plan}</b></p>
                  </div>
                  <div className="pxr-profile-quota">
                    <div><span>本月平台额度</span><b>{used}/{quota}</b></div>
                    <i className={quotaTone}><span /></i>
                    <small>{quotaPercent}% 已使用 · 远端下载和大栅格任务会优先消耗额度</small>
                  </div>
                  <div className="pxr-profile-actions">
                    <button type="button" role="menuitem" onClick={openAdminFromProfile}><UserRound size={15} />账号设置</button>
                    <button type="button" role="menuitem" onClick={handleLogout}><LogOut size={15} />退出登录</button>
                  </div>
                </>
              )}

              {profileView === 'upgrade' && (
                <div className="pxr-profile-upgrade">
                  <div className="pxr-upgrade-hero">
                    <Gem size={18} />
                    <div>
                      <strong>专业版 GIS 工作台</strong>
                      <small>为批量制图、外部数据下载和远端预发观测准备。</small>
                    </div>
                    <b>¥99/月</b>
                  </div>
                  <div className="pxr-upgrade-grid">
                    <p><CheckCircle2 size={13} />大文件上传和更多 artifact 保留</p>
                    <p><CheckCircle2 size={13} />外部下载任务队列和失败恢复</p>
                    <p><CheckCircle2 size={13} />土壤水分 / GCP 工作流观测</p>
                    <p><CheckCircle2 size={13} />管理员只读暴露面板</p>
                  </div>
                  <button type="button"><Gem size={15} />升级到专业版</button>
                  <small>升级入口仅展示界面，实际支付与权限变更需接入后端商业模块。</small>
                </div>
              )}
            </section>
            )}
          </div>
        ) : (
          <button className="pxr-login-orb" type="button" onClick={onLogin} aria-label="打开登录窗口">登录</button>
        )}
      </div>
    </header>
  );
}

function LoginDialog({
  open,
  mode,
  email,
  password,
  busy,
  error,
  onClose,
  onMode,
  onEmail,
  onPassword,
  onSubmit
}: {
  open: boolean;
  mode: LoginMode;
  email: string;
  password: string;
  busy: boolean;
  error: string;
  onClose: () => void;
  onMode: (mode: LoginMode) => void;
  onEmail: (value: string) => void;
  onPassword: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  if (!open) return null;
  const isLogin = mode === 'login';
  return (
    <div className="pxr-auth-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="pxr-auth-modal" role="dialog" aria-modal="true" aria-labelledby="pxr-auth-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="pxr-auth-modal-close" type="button" aria-label="关闭登录窗口" onClick={onClose}><X size={16} /></button>
        <header>
          <span>{isLogin ? <LogIn size={20} /> : <UserPlus size={20} />}</span>
          <div>
            <h2 id="pxr-auth-title">{isLogin ? '登录 GIS 工作台' : '创建 GIS 工作台账号'}</h2>
            <p>同步会话、上传数据索引、地图图层、RAG 命中和产物下载权限。</p>
          </div>
        </header>
        <div className="pxr-auth-mode-tabs" role="tablist" aria-label="登录方式">
          <button className={isLogin ? 'is-active' : ''} type="button" role="tab" aria-selected={isLogin} onClick={() => onMode('login')}><LogIn size={14} />登录</button>
          <button className={!isLogin ? 'is-active' : ''} type="button" role="tab" aria-selected={!isLogin} onClick={() => onMode('register')}><UserPlus size={14} />注册</button>
        </div>
        <form className="pxr-auth-form" onSubmit={onSubmit}>
          <label>
            <span>邮箱</span>
            <input autoComplete="email" type="email" value={email} onChange={(event) => onEmail(event.currentTarget.value)} placeholder="请输入邮箱" required />
          </label>
          <label>
            <span>密码</span>
            <input autoComplete={isLogin ? 'current-password' : 'new-password'} type="password" value={password} onChange={(event) => onPassword(event.currentTarget.value)} placeholder="请输入密码" required />
          </label>
          {error && <p className="pxr-auth-error"><AlertTriangle size={14} />{error}</p>}
          <button type="submit" disabled={busy}>{busy ? '处理中' : isLogin ? '登录并同步工作区' : '注册并进入工作台'}</button>
        </form>
        <footer>
          <Lock size={14} />
          <span>登录窗口只处理账号会话，不会暴露本地 .env、token 或日志内容。</span>
        </footer>
      </section>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="pxr-empty-state">
      <Circle size={9} />
      <strong>{title}</strong>
      <small>{detail}</small>
    </div>
  );
}

function PrimaryRail({
  activePanel,
  onPanelChange,
  onAdmin
}: {
  activePanel: RailPanel;
  onPanelChange: (panel: RailPanel) => void;
  onAdmin: () => void;
}) {
  const railItems = [
    [Home, '工作台', 'workspace'],
    [Layers, '图层', 'layers'],
    [Database, '数据', 'data'],
    [Map, '地图', 'map'],
    [LineChart, '观测', 'observability'],
    [Wrench, '工具', 'tools'],
    [Clock3, '历史', 'history']
  ] as const;

  return (
    <aside className="pxr-primary-rail" aria-label="主导航">
      <nav>
        {railItems.map(([Icon, label, panel]) => (
          <button
            aria-pressed={activePanel === panel}
            className={activePanel === panel ? 'is-active' : ''}
            key={label}
            title={label}
            type="button"
            onClick={() => onPanelChange(panel)}
          >
            <Icon size={20} />
          </button>
        ))}
      </nav>
      <div>
        <button type="button" title="管理员 / 运维" onClick={onAdmin}><Settings size={20} /></button>
        <button type="button" title="折叠二级栏"><ChevronDown size={20} /></button>
      </div>
    </aside>
  );
}

function DataAssetsPanel({
  activePanel,
  datasets,
  layers,
  dashboard,
  currentSessionId,
  loading,
  error,
  resultLayerState,
  onToggleLayer,
  onUploadClick,
  onRefresh
}: {
  activePanel: RailPanel;
  datasets: DatasetView[];
  layers: ResultMapLayer[];
  dashboard: WorkspaceDashboard | null;
  currentSessionId: string;
  loading: boolean;
  error: string;
  resultLayerState: ResultLayerStateMap;
  onToggleLayer: (layer: ResultMapLayer, index: number, visible: boolean) => void;
  onUploadClick: () => void;
  onRefresh: () => void;
}) {
  const panelCopy = RAIL_PANEL_COPY[activePanel];
  const knowledge = capabilityKnowledge(dashboard);
  const dashboardRecord = asRecord(dashboard);
  const workspaceName = firstText(dashboardRecord, ['workspace_name', 'workspace', 'project_name'], '演示工作区');
  const layerRows = layers.length
    ? layers
    : ([
      { id: 'boundary-empty', name: '流域边界', type: 'vector', kind: 'boundary' },
      { id: 'monitor-empty', name: '监测站点', type: 'vector', kind: 'points' },
      { id: 'rainfall-empty', name: '30年降雨均值', type: 'raster', kind: 'raster' },
      { id: 'landcover-empty', name: '2024土地覆盖', type: 'raster', kind: 'soil' }
    ] as ResultMapLayer[]);
  return (
    <aside className="pxr-left-panel">
      <section className="pxr-left-section">
        <div className="pxr-sidebar-title-row">
          <span>
            <h2>{panelCopy.title}</h2>
            <small>{panelCopy.subtitle}</small>
          </span>
          <div>
            <button type="button" title="筛选"><Search size={14} /></button>
            <button type="button" onClick={onRefresh} title="刷新"><RefreshCw size={14} /></button>
            <button type="button" onClick={onUploadClick} title="上传"><Upload size={14} /></button>
          </div>
        </div>
        <label className="pxr-search">
          <Search size={14} />
          <input placeholder={panelCopy.search} readOnly />
        </label>
        <div className="pxr-secondary-tabs">
          <button className="is-active" type="button">{panelCopy.tabs[0]}</button>
          <button type="button">{panelCopy.tabs[1]}</button>
        </div>
        {error && <p className="pxr-inline-error">{error}</p>}
      </section>

      <section className="pxr-left-section">
        <div className="pxr-rail-context-card">
          <strong>{panelCopy.hintTitle}</strong>
          <p>{panelCopy.hintDetail}</p>
          <div>
            {panelCopy.actions.map((action) => <span key={action}>{action}</span>)}
          </div>
        </div>
      </section>

      <section className="pxr-left-section">
        <div className="pxr-panel-heading">
          <h3>已上传（{datasets.length}）</h3>
          <button className="pxr-mini-add" type="button" onClick={onUploadClick}><Upload size={15} /></button>
        </div>
        <div className="pxr-file-list">
          {datasets.length === 0 && <EmptyState title={loading ? '正在读取工作区' : '暂无上传数据'} detail="上传 Shapefile、GeoTIFF 或 CSV 后会显示在这里。" />}
          {datasets.map((file) => (
            <div className="pxr-file-row" key={file.id}>
              <span className={`pxr-file-icon pxr-file-${file.tone}`}>{file.name.split('.').pop()?.slice(0, 3) || '图'}</span>
              <span className="pxr-file-copy">
                <strong>{file.name}</strong>
                <small>{file.meta}</small>
              </span>
              <StatusChip tone={file.tone === 'green' ? 'success' : file.tone === 'blue' ? 'info' : 'muted'}>{file.typeLabel}</StatusChip>
              <em>{file.size}</em>
              <MoreVertical size={13} />
            </div>
          ))}
        </div>
      </section>

      <section className="pxr-left-section pxr-layer-section">
        <div className="pxr-panel-heading">
          <h3>图层</h3>
          <small>{layers.length} / 20</small>
        </div>
        <div className="pxr-layer-list">
          {layers.length === 0 && <EmptyState title="暂无真实地图图层" detail="这里先展示图层控制样式；生成地图就绪产物后会替换为真实图层。" />}
          {layerRows.map((layer, index) => {
            const key = resultLayerKey(layer, String(index));
            const enabled = layers.length ? (resultLayerState[key]?.visible ?? true) : index < 2;
            const opacity = [100, 100, 70, 60, 80, 40][index % 6];
            return (
              <div className="pxr-layer-row" key={key}>
                <span className="pxr-drag-handle">::</span>
                <input checked={enabled} disabled={!layers.length} onChange={(event) => onToggleLayer(layer, index, event.currentTarget.checked)} type="checkbox" />
                <span className={`pxr-layer-symbol pxr-layer-${layer.kind || layer.type || 'boundary'}`} />
                <strong>{layer.name}</strong>
                <span className="pxr-opacity-track"><i style={{ width: `${opacity}%` }} /></span>
                <em>{opacity}%</em>
                <MoreVertical size={13} />
              </div>
            );
          })}
        </div>
      </section>

      <section className="pxr-left-section">
        <h3>坐标系统</h3>
        <div className="pxr-crs-card">
          <MapPin size={21} />
          <span>
            <strong>{datasets[0]?.crs || 'EPSG:3857'}</strong>
            <small>{datasets[0]?.crs ? '当前数据坐标系' : 'WGS 84 / 伪墨卡托'}</small>
          </span>
          <ChevronDown size={14} />
        </div>
      </section>

      <section className="pxr-left-section pxr-session-card">
        <h3>工作区</h3>
        <div className="pxr-session-grid">
          <span>名称</span><b>{workspaceName}</b>
          <span>会话</span><b>{currentSessionId || dashboard?.current_session_id || '--'}</b>
          <span>数据集</span><b>{datasets.length}</b>
        </div>
        <button type="button" onClick={onRefresh}>刷新会话</button>
      </section>

      <section className="pxr-left-section pxr-rag-card">
        <h3>知识库（RAG）</h3>
        {knowledge.length === 0 ? (
          <EmptyState title="暂无命中知识" detail="对话检索或能力配置加载后显示前三条文档。" />
        ) : (
          <ol>
            {knowledge.map((item) => <li key={item}>{item}</li>)}
          </ol>
        )}
      </section>
    </aside>
  );
}

function PipelineBoard({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="pxr-pipeline-board">
      {steps.map((step, index) => {
        const StepIcon = step.icon;
        return (
          <div className="pxr-step-card" key={step.title}>
            <StepIcon size={24} />
            <span>
              <strong>{step.title}</strong>
              <small>{step.detail} <Circle size={7} className={step.ok ? 'pxr-dot-green' : 'pxr-dot-amber'} /></small>
            </span>
            {index < steps.length - 1 && <i>→</i>}
          </div>
        );
      })}
    </div>
  );
}

function MapLegend({ layers }: { layers: ResultMapLayer[] }) {
  return (
    <div className="pxr-map-legend">
      <h4>图例</h4>
      {layers.length === 0 && <div><i className="pxr-layer-gray" />暂无图层</div>}
      {layers.slice(0, 6).map((layer, index) => (
        <div key={layer.id || layer.name}>
          <i style={{ background: ['#1877f2', '#f97316', '#58b947', '#38bdf8', '#f59e0b', '#ef4444'][index % 6] }} />
          {layer.name}
        </div>
      ))}
    </div>
  );
}

function MapCanvas({
  userId,
  sessionId,
  layers,
  resultLayerState,
  onResultLayersChange,
  onChatContextChange
}: {
  userId: string;
  sessionId: string;
  layers: ResultMapLayer[];
  resultLayerState: ResultLayerStateMap;
  onResultLayersChange: (layers: ResultMapLayer[]) => void;
  onChatContextChange: (patch: Partial<ChatContextPayload>) => void;
}) {
  const [drawMode, setDrawMode] = useState(false);
  const [mapCommand, setMapCommand] = useState<MapCommand | null>(null);
  const triggerCommand = (type: 'zoomIn' | 'zoomOut' | 'locate' | 'resetBearing' | 'clearDraw') => {
    setMapCommand({ type, id: Date.now() });
    window.setTimeout(() => setMapCommand(null), 0);
  };
  const hasLiveMap = Boolean(userId && layers.length > 0);
  return (
    <section className={`pxr-map-shell ${hasLiveMap ? 'is-live' : ''}`}>
      <label className="pxr-map-search">
        <Search size={17} />
        <input placeholder="搜索地图" readOnly />
      </label>
      <div className="pxr-map-toolbar-left">
        <button type="button" title="选择"><MousePointer2 size={18} /></button>
        <button type="button" title="平移"><Home size={18} /></button>
        <button type="button" title="框选"><Square size={18} /></button>
        <button type="button" title="多边形选择"><Box size={18} /></button>
        <button type="button" title="查询"><MapPin size={18} /></button>
        <button type="button" title="量测" onClick={() => setDrawMode(!drawMode)}><Ruler size={18} /></button>
        <button type="button" title="清空绘制" onClick={() => triggerCommand('clearDraw')}><Circle size={18} /></button>
        <button type="button" title="更多"><MoreHorizontal size={18} /></button>
      </div>
      <div className="pxr-map-toolbar-top">
        <button className="is-active" type="button">2D</button>
        <button type="button">3D</button>
        <IconButton title="图层"><Layers size={14} /></IconButton>
      </div>
      <div className="pxr-map-bg">
        {hasLiveMap ? (
          <div className="pxr-map-stage-embed">
            <MapStage
              theme="light"
              basemap="standard"
              userId={userId}
              sessionId={sessionId}
              drawMode={drawMode}
              setDrawMode={setDrawMode}
              layerVisibility={EMPTY_LAYER_VISIBILITY}
              resultLayerState={resultLayerState}
              mapCommand={mapCommand}
              onResultLayersChange={onResultLayersChange}
              onChatContextChange={onChatContextChange}
              allowFallbackStations={false}
            />
          </div>
        ) : (
          <>
            <div className="pxr-river pxr-river-a" />
            <div className="pxr-river pxr-river-b" />
            <div className="pxr-watershed-shape"><span className="pxr-shape-ridges" /></div>
            {[
              ['29%', '24%', 'orange'],
              ['43%', '31%', 'orange'],
              ['62%', '29%', 'green'],
              ['37%', '58%', 'orange'],
              ['55%', '67%', 'orange'],
              ['68%', '49%', 'green']
            ].map(([left, top, tone]) => (
              <span className={`pxr-map-point pxr-point-${tone}`} key={`${left}-${top}`} style={{ left, top }} />
            ))}
            <div className="pxr-map-empty-canvas">
              <Map size={42} />
              <strong>{userId ? '暂无可渲染地图图层' : '等待登录与工作区数据'}</strong>
              <span>上传数据或执行 GIS 任务后，地图就绪图层会自动显示在这里。</span>
            </div>
          </>
        )}
        <div className="pxr-map-tooltip">
          <header><strong>{layers[0]?.name || '子流域 12B'}</strong><X size={12} /></header>
          <p><b>面积</b><span>{layers[0]?.bounds ? '已读取' : '45.2 km²'}</span></p>
          <p><b>图层</b><span>{layers.length || '--'}</span></p>
          <a>查看详情</a>
        </div>
        <MapLegend layers={layers} />
        <div className="pxr-map-status">
          <h4>地图状态</h4>
          <p><CheckCircle2 size={13} />图层：{layers.length ? `${layers.length} 个` : '空'}</p>
          <p><CheckCircle2 size={13} />会话：{sessionId || '--'}</p>
          <p><Circle size={9} />实时轮询：8s</p>
        </div>
        <div className="pxr-map-zoom">
          <button type="button" onClick={() => triggerCommand('zoomIn')}><ZoomIn size={16} /></button>
          <button type="button" onClick={() => triggerCommand('zoomOut')}><ZoomOut size={16} /></button>
          <button type="button" onClick={() => triggerCommand('resetBearing')}><Home size={16} /></button>
        </div>
        <div className="pxr-map-3d"><Settings size={17} /><b>3D</b></div>
        <div className="pxr-scale-bar"><span />0&nbsp;&nbsp;&nbsp;&nbsp;5&nbsp;&nbsp;&nbsp;&nbsp;10&nbsp;&nbsp;&nbsp;&nbsp;15 km</div>
        <div className="pxr-mini-map" />
        <div className="pxr-coordinates">会话：{sessionId || '--'}&nbsp;&nbsp;&nbsp;图层：{layers.length}</div>
      </div>
    </section>
  );
}

function ArtifactsDrawer({
  artifacts,
  onDownloadArtifact
}: {
  artifacts: ArtifactView[];
  onDownloadArtifact: (artifact: ArtifactView) => void;
}) {
  return (
    <section className="pxr-artifact-drawer">
      <nav className="pxr-result-tabs">
        <strong>产物</strong>
        <button className="is-active" type="button">全部 <b>{artifacts.length}</b></button>
        <button type="button">地图</button>
        <button type="button">栅格</button>
        <button type="button">报告</button>
        <button type="button">数据</button>
        <span />
        <button type="button">排序：更新时间</button>
        <button type="button"><X size={14} /></button>
      </nav>
      <div className="pxr-artifact-grid">
        {artifacts.length === 0 && <EmptyState title="暂无产物" detail="任务执行完成后，报告、地图、栅格和表格产物会显示在这里。" />}
        {artifacts.slice(0, 6).map((artifact, index) => (
          <article className="pxr-artifact-card" key={artifact.id}>
            <h4>{index + 1}. {artifact.title}</h4>
            <small>{artifact.type}</small>
            <div className={`pxr-artifact-preview pxr-preview-${artifact.preview}`}>
              {artifact.preview === 'json' && <FileText size={48} />}
              {artifact.preview === 'gate' && <Shield size={52} />}
            </div>
            <p>{artifact.meta}<span>状态：完成</span></p>
            <footer>
              <button type="button"><Eye size={13} />预览</button>
              <button type="button" onClick={() => onDownloadArtifact(artifact)} disabled={!artifact.artifactId && !artifact.downloadUrl}><Download size={13} />下载</button>
            </footer>
          </article>
        ))}
        <article className="pxr-artifact-card pxr-new-artifact">
          <PlusIcon />
          <span>新建产物</span>
        </article>
      </div>
      <div className="pxr-artifact-summary">
        <span>共 {artifacts.length} 个产物</span><span>来源：工作区 / 对话结果</span>
        <button type="button" disabled={artifacts.length === 0}><Download size={14} />全部下载</button>
      </div>
    </section>
  );
}

function CapabilityRail() {
  return (
    <div className="pxr-capability-card">
      {CAPABILITY_ITEMS.map((item, index) => (
        <span key={item}>
          <i>{index === 0 ? '链' : <CheckCircle2 size={12} />}</i>
          <small>{item}</small>
        </span>
      ))}
    </div>
  );
}

function PlusIcon() {
  return (
    <span className="pxr-plus-icon">
      <span />
      <span />
    </span>
  );
}

function AdminOpsDock({
  exposure,
  dashboard,
  jobs,
  onAdmin
}: {
  exposure: AdminExposure | null;
  dashboard: WorkspaceDashboard | null;
  jobs: DownloadJob[];
  onAdmin?: () => void;
}) {
  const runtime = dashboard?.runtime_status || {};
  const latency = firstText(runtime, ['latency_p95_ms', 'p95_ms'], '--');
  const errorRate = firstText(runtime, ['error_rate'], '--');
  const throughput = firstText(runtime, ['throughput_per_min', 'rpm'], jobs.length ? String(jobs.length) : '--');

  return (
    <section className="pxr-admin-ops-dock">
      <header>
        <h3>管理 / 运维</h3>
        {onAdmin ? <button type="button" onClick={onAdmin}>打开完整面板</button> : <span>管理员面板</span>}
      </header>
      <div className="pxr-ops-kpis">
        <p><span>暴露比例</span><b>{exposure?.requested_percent ?? 0}%</b></p>
        <p><span>灰度状态</span><b>{exposure?.eligible_for_user_exposure ? '通过' : '观察'}</b></p>
        <p><span>回滚保护</span><b>{exposure?.rollback_requested ? '已开启' : '正常'}</b></p>
      </div>
      <div className="pxr-ops-sparks">
        <p><span>延迟 P95</span><b>{latency}{latency !== '--' ? 'ms' : ''}</b><i /></p>
        <p><span>错误率</span><b>{errorRate}</b><i /></p>
        <p><span>吞吐量</span><b>{throughput}</b><i /></p>
      </div>
      <div className="pxr-ops-gates">
        {['数据质量门禁', '结构漂移门禁', '冒烟测试'].map((name) => (
          <span key={name}><CheckCircle2 size={12} />{name}<b>通过</b></span>
        ))}
      </div>
    </section>
  );
}

function CopilotEmptyState({ onSend }: { onSend: (prompt: string) => void }) {
  const prompts = [
    '识别上传数据并生成地图',
    '裁剪矢量并导出产物',
    '表格经纬度转点',
    '检查 CRS 与图层范围'
  ];

  return (
    <div className="pxr-copilot-empty">
      <div className="pxr-streaming-orbit">
        <span />
        <span />
        <span />
      </div>
      <strong>等待 GIS 任务</strong>
      <p>可以上传数据，也可以直接描述制图、裁剪、统计、RAG 查询或工作流执行需求。</p>
      <div>
        {prompts.map((prompt) => (
          <button key={prompt} type="button" onClick={() => onSend(prompt)}>{prompt}</button>
        ))}
      </div>
    </div>
  );
}

function LivePlanCard({
  sending,
  activeJobs,
  workflowRows,
  interactionMode
}: {
  sending: boolean;
  activeJobs: DownloadJob[];
  workflowRows: ReturnType<typeof buildWorkflowRows>;
  interactionMode: InteractionMode;
}) {
  const modeCopy = INTERACTION_MODE_COPY[interactionMode];
  const stepLabels = modeCopy.steps;
  const eventDepth = Math.min(stepLabels.length - 1, workflowRows.length);
  const activeIndex = activeJobs.length ? Math.max(3, eventDepth) : sending ? Math.max(1, eventDepth) : eventDepth;
  const currentJob = activeJobs[0];
  const currentDetail = currentJob
    ? currentJob.stage || currentJob.status_label || currentJob.output_name || currentJob.resource_type || '工具正在执行'
    : sending
      ? modeCopy.detail
      : interactionMode === 'tool_enabled' ? '运行事件已同步' : '等待新的对话输入';
  return (
    <article className="pxr-live-plan-card">
      <header>
        <span className="pxr-live-plan-pulse" />
        <div>
          <strong>{modeCopy.planTitle}</strong>
          <small>{activeJobs.length ? `${activeJobs.length} 个任务运行中 · ${currentDetail}` : currentDetail}</small>
        </div>
        <StatusChip tone={activeJobs.length || sending ? 'warning' : 'info'}>{activeJobs.length || sending ? '运行中' : '已同步'}</StatusChip>
      </header>
      <ol>
        {stepLabels.map((label, index) => (
          <li className={index < activeIndex ? 'is-done' : index === activeIndex ? 'is-running' : ''} key={label}>
            <span>{index < activeIndex ? <CheckCircle2 size={12} /> : index + 1}</span>
            <b>{label}</b>
            <small>{index === activeIndex ? '实时更新' : index < activeIndex ? '完成' : '等待'}</small>
          </li>
        ))}
      </ol>
    </article>
  );
}

function TaskPanel({
  messages,
  dashboard,
  jobs,
  chatContext,
  currentSessionId,
  interactionMode,
  interactionModeBusy,
  interactionModeError,
  composerText,
  sending,
  uploading,
  chatError,
  onComposerText,
  onInteractionMode,
  onSend,
  onUploadClick
}: {
  messages: ChatMessage[];
  dashboard: WorkspaceDashboard | null;
  jobs: DownloadJob[];
  chatContext: ChatContextPayload;
  currentSessionId: string;
  interactionMode: InteractionMode;
  interactionModeBusy: boolean;
  interactionModeError: string;
  composerText: string;
  sending: boolean;
  uploading: boolean;
  chatError: string;
  onComposerText: (value: string) => void;
  onInteractionMode: (mode: InteractionMode) => void;
  onSend: (prompt: string) => void;
  onUploadClick: () => void;
}) {
  const [voiceNotice, setVoiceNotice] = useState('');
  const workflowRows = buildWorkflowRows(dashboard, jobs);
  const knowledge = capabilityKnowledge(dashboard);
  const finalSummary = latestAssistantSummary(messages, dashboard);
  const activeJobs = jobs.filter((job) => !['completed', 'succeeded', 'failed', 'canceled'].includes(String(job.status || job.state || '').toLowerCase()));
  const failedJobs = jobs.filter((job) => ['failed', 'error', 'canceled'].includes(String(job.status || job.state || '').toLowerCase()));
  const hasStreamingMessage = messages.some((message) => Boolean(message.meta?.streaming));
  const hasTaskActivity = sending || hasStreamingMessage || activeJobs.length > 0;
  const hasContext = hasTaskActivity || messages.length > 0 || Boolean(currentSessionId || chatContext.active_dataset_id || chatContext.selected_layer_id || chatContext.selected_map_bounds || dashboard?.datasets?.length);
  const hasKnowledgePanel = hasTaskActivity || knowledge.length > 0;
  const hasFinalPanel = Boolean(finalSummary || chatError || failedJobs.length);
  const showToolTimeline = interactionMode === 'tool_enabled' || workflowRows.length > 0 || activeJobs.length > 0;
  const showCapabilityRail = hasTaskActivity && showToolTimeline;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSend(composerText);
  };
  const showVoiceNotice = () => {
    setVoiceNotice('语音输入入口已保留，当前演示版需要接入浏览器语音权限后启用。');
    window.setTimeout(() => setVoiceNotice(''), 3200);
  };
  return (
    <aside className="pxr-task-panel">
      <header className="pxr-task-header">
        <div className="pxr-task-title-row">
          <h2>智能助手</h2>
          <div className="pxr-mode-switch pxr-mode-switch-header" aria-label="会话模式">
            <button
              className={interactionMode === 'chat_only' ? 'is-active' : ''}
              data-testid="interaction-mode-chat"
              disabled={interactionModeBusy || sending}
              type="button"
              title="聊天模式"
              aria-label="聊天模式"
              aria-pressed={interactionMode === 'chat_only'}
              onClick={() => onInteractionMode('chat_only')}
            >
              <MessageCircle size={14} />
            </button>
            <button
              className={interactionMode === 'tool_enabled' ? 'is-active' : ''}
              data-testid="interaction-mode-tool"
              disabled={interactionModeBusy || sending}
              type="button"
              title="执行模式"
              aria-label="执行模式"
              aria-pressed={interactionMode === 'tool_enabled'}
              onClick={() => onInteractionMode('tool_enabled')}
            >
              <Wrench size={14} />
            </button>
          </div>
        </div>
        <div>
          <StatusChip tone={sending ? 'warning' : 'success'}>{sending ? '生成中' : '就绪'}</StatusChip>
          <IconButton title="固定"><Bell size={14} /></IconButton>
          <IconButton title="刷新"><RefreshCw size={14} /></IconButton>
          <IconButton title="更多"><MoreVertical size={14} /></IconButton>
        </div>
      </header>

      <div className="pxr-task-scroll">
        <section className="pxr-chat-stream">
          {messages.length === 0 && <CopilotEmptyState onSend={onSend} />}
          {messages.slice(-8).map((message, index) => (
            <div className={`pxr-message ${message.role === 'user' ? 'pxr-user-message' : 'pxr-assistant-message'}`} key={message.id || message.message_id || `${message.role}-${index}`}>
              <span>{message.role === 'user' ? '用户请求' : message.role === 'assistant' ? '智能体回复' : '系统'}</span>
              <p>{compactText(message.content || '正在生成', message.role === 'assistant' ? 240 : 150)}</p>
              <time>{shortTime(message.created_at)}</time>
            </div>
          ))}
          {hasTaskActivity && (
            <LivePlanCard
              sending={sending || hasStreamingMessage}
              activeJobs={activeJobs}
              workflowRows={workflowRows}
              interactionMode={interactionMode}
            />
          )}
        </section>

        {hasContext && (
          <section className="pxr-context-block">
            <h3>提示上下文</h3>
            <div className="pxr-context-chips">
              <span>会话：{currentSessionId || '--'}</span>
              <span>数据集：{String(chatContext.active_dataset_id || dashboard?.datasets?.length || '--')}</span>
              <span>图层：{String(chatContext.selected_layer_id || '--')}</span>
              <span>地图范围：{chatContext.selected_map_bounds ? '已同步' : '未选择'}</span>
            </div>
          </section>
        )}

        {hasKnowledgePanel && (
          <section className="pxr-context-block">
            <div className="pxr-section-split">
              <h3>RAG 知识（Top 3）</h3>
              <a>查看全部</a>
            </div>
            {knowledge.length === 0 ? (
              <EmptyState title="等待检索" detail="任务执行时将展示真实检索命中的知识片段。" />
            ) : (
              <ol className="pxr-rag-list">
                {knowledge.map((item, index) => <li key={item}>{index + 1}. {item}<span>已启用</span></li>)}
              </ol>
            )}
          </section>
        )}

        {hasContext && (
          <div className="pxr-memory-card">
            <strong>会话记忆</strong>
            <span>CRS:{String(chatContext.selected_feature_properties?.crs || '--')}</span>
            <span>会话:{currentSessionId ? '已绑定' : '未绑定'}</span>
            <span>图层:{String(chatContext.selected_layer_id || '--')}</span>
            <span>焦点:{String(chatContext.user_focus_hint || '--')}</span>
          </div>
        )}
        {showCapabilityRail && <CapabilityRail />}

        {showToolTimeline && (
          <section className="pxr-timeline-block">
            <h3>工具执行</h3>
            <div className="pxr-workflow-spine">
              {workflowRows.length === 0 && <EmptyState title="等待执行模式" detail="切换到执行后，下载、工作流和 GIS 工具事件会出现在这里。" />}
              {workflowRows.map((row, index) => (
                <div className="pxr-workflow-row" key={`${row.title}-${index}`}>
                  <i>{index + 1}</i>
                  <div>
                    <strong>{row.title}</strong>
                    <small>{row.detail}</small>
                  </div>
                  <time>{row.time}</time>
                  <b>{statusLabel(row.state)}</b>
                </div>
              ))}
            </div>
          </section>
        )}

        {activeJobs.length > 0 && (
          <section className="pxr-download-confirm">
            <AlertTriangle size={18} />
            <div>
              <strong>外部下载安全确认</strong>
              <p>{`${activeJobs.length} 个下载/外部数据任务正在观察中。`}</p>
              <label><input checked readOnly type="checkbox" />仅在任务明确需要时触发外部下载</label>
            </div>
            <button type="button"><Download size={14} />查看任务</button>
          </section>
        )}

        {(chatError || failedJobs.length > 0) && (
          <section className="pxr-recovery-card">
            <SparkleIcon />
            <div>
              <strong>如遇失败，尝试恢复</strong>
              <p>{chatError || `${failedJobs.length} 个任务需要查看结构化错误和重试建议。`}</p>
              <a>查看日志</a>
            </div>
          </section>
        )}
      </div>

      <footer className="pxr-final-answer">
        {hasFinalPanel && (
          <div className="pxr-final-summary-card">
            <h3>最终答案（摘要）</h3>
            <p>{finalSummary ? compactText(finalSummary, 190) : '任务完成后，摘要、产物和地图入口会在这里更新。'}</p>
            {chatError && <p className="pxr-inline-error">{chatError}</p>}
            <div>
              <button type="button"><FileText size={15} />查看报告</button>
              <button type="button"><Map size={15} />打开地图 <ChevronDown size={13} /></button>
              <button type="button"><Download size={15} />导出产物 <ChevronDown size={13} /></button>
            </div>
          </div>
        )}
        {(interactionModeError || voiceNotice) && <div className="pxr-composer-meta"><b>{interactionModeError || voiceNotice}</b></div>}
        <form className="pxr-chat-composer" onSubmit={submit}>
          <button className="pxr-composer-plus" type="button" onClick={onUploadClick} title={uploading ? '正在上传' : '上传文件'} aria-label={uploading ? '正在上传' : '上传文件'}>
            <Plus size={20} />
          </button>
          <div className="pxr-composer-input-wrap">
            <input value={composerText} onChange={(event) => onComposerText(event.currentTarget.value)} placeholder="有问题，尽管问" />
          </div>
          <button className="pxr-voice-button" type="button" title="语音输入" aria-label="语音输入" onClick={showVoiceNotice}><Mic size={16} /></button>
          <button className="pxr-agent-action-button" type="submit" disabled={sending || !composerText.trim()} title="发送" aria-label="发送">
            <Send size={18} />
          </button>
        </form>
      </footer>
    </aside>
  );
}

function SparkleIcon() {
  return (
    <span className="pxr-sparkle-icon">
      <Zap size={16} />
    </span>
  );
}

function LegacyIntegrationContract(_: {
  sessionId: string;
  onSessionChange: (sessionId: string) => void;
  chatContext: ChatContextPayload;
  onOpenMap: () => void;
}) {
  return null;
}

function WorkbenchView({
  user,
  dashboard,
  jobs,
  exposure,
  messages,
  currentSessionId,
  chatContext,
  resultLayers,
  resultLayerState,
  resultPanel,
  interactionMode,
  interactionModeBusy,
  interactionModeError,
  loading,
  error,
  composerText,
  sending,
  uploading,
  chatError,
  fileInputRef,
  onAdmin,
  onLogin,
  onLogout,
  onRefresh,
  onUploadFiles,
  onUploadClick,
  onComposerText,
  onInteractionMode,
  onSend,
  onToggleLayer,
  onResultLayersChange,
  onChatContextChange,
  onDownloadArtifact
}: {
  user: CommercialUser | null;
  dashboard: WorkspaceDashboard | null;
  jobs: DownloadJob[];
  exposure: AdminExposure | null;
  messages: ChatMessage[];
  currentSessionId: string;
  chatContext: ChatContextPayload;
  resultLayers: ResultMapLayer[];
  resultLayerState: ResultLayerStateMap;
  resultPanel: ResultPanel | null;
  interactionMode: InteractionMode;
  interactionModeBusy: boolean;
  interactionModeError: string;
  loading: boolean;
  error: string;
  composerText: string;
  sending: boolean;
  uploading: boolean;
  chatError: string;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onAdmin: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onRefresh: () => void;
  onUploadFiles: (files: FileList | null) => void;
  onUploadClick: () => void;
  onComposerText: (value: string) => void;
  onInteractionMode: (mode: InteractionMode) => void;
  onSend: (prompt: string) => void;
  onToggleLayer: (layer: ResultMapLayer, index: number, visible: boolean) => void;
  onResultLayersChange: (layers: ResultMapLayer[]) => void;
  onChatContextChange: (patch: Partial<ChatContextPayload>) => void;
  onDownloadArtifact: (artifact: ArtifactView) => void;
}) {
  const [activePanel, setActivePanel] = useState<RailPanel>('workspace');
  const datasets = datasetViews(dashboard);
  const artifacts = artifactViews(dashboard, resultPanel);
  const steps = buildPipeline(dashboard, jobs, resultLayers, exposure);
  return (
    <main className="pxr-app pxr-workbench">
      <input ref={fileInputRef} className="pxr-hidden-input" multiple type="file" onChange={(event) => onUploadFiles(event.currentTarget.files)} />
      <WorkbenchTopBar onAdmin={onAdmin} onLogin={onLogin} onLogout={onLogout} exposure={exposure} dashboard={dashboard} user={user} />
      <PrimaryRail activePanel={activePanel} onPanelChange={setActivePanel} onAdmin={onAdmin} />
      <DataAssetsPanel
        activePanel={activePanel}
        datasets={datasets}
        layers={resultLayers}
        dashboard={dashboard}
        currentSessionId={currentSessionId}
        loading={loading}
        error={error}
        resultLayerState={resultLayerState}
        onToggleLayer={onToggleLayer}
        onUploadClick={onUploadClick}
        onRefresh={onRefresh}
      />
      <div className="pxr-main-column">
        <MapCanvas
          userId={user?.user_id || ''}
          sessionId={currentSessionId}
          layers={resultLayers}
          resultLayerState={resultLayerState}
          onResultLayersChange={onResultLayersChange}
          onChatContextChange={onChatContextChange}
        />
        <section className="pxr-bottom-dock">
          <PipelineBoard steps={steps} />
          <ArtifactsDrawer artifacts={artifacts} onDownloadArtifact={onDownloadArtifact} />
        </section>
      </div>
      <TaskPanel
        messages={messages}
        dashboard={dashboard}
        jobs={jobs}
        chatContext={chatContext}
        currentSessionId={currentSessionId}
        interactionMode={interactionMode}
        interactionModeBusy={interactionModeBusy}
        interactionModeError={interactionModeError}
        composerText={composerText}
        sending={sending}
        uploading={uploading}
        chatError={chatError}
        onComposerText={onComposerText}
        onInteractionMode={onInteractionMode}
        onSend={onSend}
        onUploadClick={onUploadClick}
      />
    </main>
  );
}

function AdminHeader({ onWorkbench, exposure }: { onWorkbench: () => void; exposure: AdminExposure | null }) {
  return (
    <header className="pxr-admin-header">
      <div className="pxr-admin-title">
        <Shield size={30} />
        <h1>管理控制台</h1>
        <span>只读</span>
      </div>
      <div className="pxr-admin-meta">
        <label>环境<button type="button">{statusLabel(exposure?.environment || 'staging')} <ChevronDown size={14} /></button></label>
        <label>分支与提交<strong>main&nbsp;&nbsp;/&nbsp;&nbsp;<a>--</a></strong><Copy size={16} /></label>
        <label>最后检查<strong>{dateTime(exposure?.checked_at)}</strong><Clock3 size={16} /></label>
      </div>
      <button className="pxr-readonly-button" type="button"><Lock size={16} />只读</button>
      <button className="pxr-refresh-button" type="button"><RefreshCw size={17} />刷新</button>
      <button className="pxr-workbench-shortcut" type="button" onClick={onWorkbench}>工作台</button>
    </header>
  );
}

function AdminSidebar() {
  const navItems = [
    [LineChart, '运行暴露', '灰度比例与路由', true],
    [Shield, '质量门禁', '观测与冒烟检查', false],
    [Activity, '观测窗口', '流量与质量指标', false],
    [BookOpen, '知识 / RAG', '检索知识配置', false],
    [Clock3, '安全 / 回滚', '回滚与只读确认', false],
    [FileText, '证据文件', '报告与审计产物', false]
  ] as const;

  return (
    <aside className="pxr-admin-sidebar">
      <nav>
        {navItems.map(([Icon, title, subtitle, active]) => (
          <button className={active ? 'is-active' : ''} key={title} type="button">
            <Icon size={23} />
            <span><strong>{title}</strong><small>{subtitle}</small></span>
          </button>
        ))}
      </nav>
      <section className="pxr-audit-card">
        <h3>审计日志</h3>
        {['工作区刷新', '暴露检查', '地图图层轮询', '对话流同步', '产物同步'].map((item, index) => (
          <p key={item}>
            <span>{shortTime(new Date(Date.now() - index * 240000).toISOString())}</span>
            <a>{item}</a>
            <small>{['工作区刷新', '只读检查', '图层轮询', '对话同步', '产物同步'][index]}</small>
          </p>
        ))}
        <a className="pxr-audit-link">查看完整审计日志</a>
      </section>
    </aside>
  );
}

function SectionHeader({ index, title, subtitle, badge }: { index: number; title: string; subtitle: string; badge?: string }) {
  return (
    <header className="pxr-admin-section-title">
      <span>{index}</span>
      <h2>{title}</h2>
      <small>{subtitle}</small>
      {badge && <StatusChip tone="success">{badge}</StatusChip>}
    </header>
  );
}

function RuntimeExposureSection({ exposure }: { exposure: AdminExposure | null }) {
  const reasons = exposure?.blocking_reasons_human || exposure?.reasons || [];
  return (
    <section className="pxr-admin-section pxr-runtime-section">
      <SectionHeader index={1} title="运行暴露" subtitle="灰度比例与路由" />
      <div className="pxr-runtime-metrics">
        <div><span>环境</span><strong>{statusLabel(exposure?.environment)}</strong></div>
        <div><span>暴露比例</span><strong className="pxr-big-green">{exposure?.requested_percent ?? 0}%</strong></div>
        <div><span>是否合格</span><strong className="pxr-green-check"><CheckCircle2 size={22} />{exposure?.eligible_for_user_exposure ? '是' : '否'}</strong></div>
        <div><span>回滚开关</span><strong className={exposure?.rollback_requested ? 'pxr-on-state' : 'pxr-off-state'}>{exposure?.rollback_requested ? '已开启' : '未开启'}</strong><small>{exposure?.rollback_requested ? '主动路由已阻断' : '主动路由可观察'}</small></div>
        <div><span>状态</span><StatusChip tone={exposure?.eligible_for_user_exposure ? 'success' : 'warning'}>{statusLabel(exposure?.recommendation, '仅观察')}</StatusChip></div>
        <div><span>阻塞原因</span><strong>{reasons.length ? reasons.length : '无'}</strong></div>
      </div>
      <table className="pxr-admin-table pxr-routing-table">
        <thead>
          <tr><th>路由对比（示例）</th><th>总请求</th><th>主动路由（新版智能体）</th><th>比例</th><th>传统路由</th><th>比例</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr><td>暴露策略</td><td>--</td><td className="pxr-soft-green">{exposure?.eligible_for_user_exposure ? '允许' : '阻断'}</td><td className="pxr-soft-green">{exposure?.requested_percent ?? 0}%</td><td>{100 - (exposure?.requested_percent ?? 0)}%</td><td>--</td><td>{reasons.length ? reasons.join('；') : '不要在未获批准的情况下提高暴露比例'}</td></tr>
        </tbody>
      </table>
    </section>
  );
}

function GatesSection({ exposure }: { exposure: AdminExposure | null }) {
  const rows = buildGateRows(exposure);
  return (
    <section className="pxr-admin-section">
      <div className="pxr-admin-section-line">
        <SectionHeader index={2} title="质量门禁" subtitle="观测与冒烟检查" badge={exposure?.eligible_for_user_exposure ? '门禁通过' : undefined} />
        <span>暴露建议：<b>{statusLabel(exposure?.recommendation)}</b></span>
        <time>最近检查：{dateTime(exposure?.checked_at)}</time>
      </div>
      <table className="pxr-admin-table">
        <thead>
          <tr><th>门禁</th><th>类型</th><th>频率</th><th>状态</th><th>结果</th><th>时间</th></tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={6}>管理员暴露接口暂不可用或无权限，仅显示只读空状态。</td></tr>
          ) : rows.map(([gate, type, frequency, status, result, time]) => (
            <tr key={gate}>
              <td><strong>{gate}</strong></td>
              <td>{type}</td>
              <td>{frequency}</td>
              <td><StatusChip tone={statusTone(status)}>{status}</StatusChip></td>
              <td>{result}</td>
              <td>{dateTime(time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TrafficQualitySection({ dashboard, jobs, layers }: { dashboard: WorkspaceDashboard | null; jobs: DownloadJob[]; layers: ResultMapLayer[] }) {
  const runtime = dashboard?.runtime_status || {};
  const artifactCount = dashboard?.artifacts?.length || 0;
  const metrics = [
    ['错误率', '运行错误比例', firstText(runtime, ['error_rate'], '--'), '', 'green'],
    ['延迟（毫秒）', '第 95 百分位', firstText(runtime, ['latency_p95_ms', 'p95_ms'], '--'), '', 'ink'],
    ['产物数量', '报告、地图与数据', String(artifactCount), '', 'green'],
    ['地图图层', '可渲染图层', String(layers.length), '', 'green'],
    ['外部下载任务', '下载队列数量', String(jobs.length), '', jobs.length ? 'amber' : 'ink'],
    ['会话消息', '对话消息数量', String(dashboard?.messages?.length || 0), '', 'ink']
  ];

  return (
    <section className="pxr-admin-section">
      <SectionHeader index={3} title="观测窗口" subtitle="流量与质量指标" />
      <div className="pxr-quality-grid">
        {metrics.map(([title, subtitle, value, delta, tone]) => (
          <div className={`pxr-quality-metric pxr-quality-${tone}`} key={title}>
            <span>{title}</span>
            <small>{subtitle}</small>
            <strong>{value}</strong>
            {delta && <em>{delta}</em>}
          </div>
        ))}
        <div className="pxr-task-type-card">
          <h3>任务类型分布（Top 5）</h3>
          {Object.entries(dashboard?.dataset_type_counts || {}).slice(0, 5).map(([name, value]) => (
            <p key={name}><span>{name}</span><b>{String(value)}</b></p>
          ))}
          {Object.keys(dashboard?.dataset_type_counts || {}).length === 0 && <p><span>暂无数据</span><b>--</b></p>}
        </div>
      </div>
    </section>
  );
}

function RollbackSection({ exposure }: { exposure: AdminExposure | null }) {
  return (
    <section className="pxr-admin-section pxr-rollback-section">
      <SectionHeader index={4} title="回滚" subtitle="回滚与只读确认" />
      <div className="pxr-rollback-grid">
        <div className="pxr-rollback-warning">
          <AlertTriangle size={28} />
          <div>
            <strong>回滚操作将停止新版智能体的流量。</strong>
            <p>请仅在需要时执行，并遵循变更管理。</p>
          </div>
        </div>
        <table className="pxr-admin-table pxr-checklist-table">
          <tbody>
            <tr><td>1</td><td>设置系统变量</td><td>GIS_AGENT_RUNTIME_ROLLBACK=1</td></tr>
            <tr><td>2</td><td>重启 / 重新加载服务</td><td>让配置重新生效</td></tr>
            <tr><td>3</td><td>只读检查（管理员验证）</td><td>确认主动路由比例为 0%</td></tr>
          </tbody>
        </table>
        <div className="pxr-readonly-result">
          <h3>只读检查结果</h3>
          <p><span>回滚标志</span><b>{exposure?.rollback_requested ? '已设置' : '未设置'}</b><CheckCircle2 size={17} /></p>
          <p><span>主动路由比例</span><b>{exposure?.rollback_requested ? '0% 已阻断' : `${exposure?.requested_percent ?? 0}%`}</b><CheckCircle2 size={17} /></p>
          <p><span>新版智能体状态</span><b>{exposure?.eligible_for_user_exposure ? '可暴露' : '阻断 / 观察'}</b><CheckCircle2 size={17} /></p>
          <p><span>检查时间</span><b>{dateTime(exposure?.checked_at)}</b></p>
        </div>
        <aside className="pxr-readonly-notice">
          <Lock size={30} />
          <strong>只读提醒</strong>
          <p>管理员控制台为只读说明，不提供生产环境的直接修改操作。</p>
          <span>不允许在此直接修改运行环境。</span>
        </aside>
      </div>
    </section>
  );
}

function AdminView({
  onWorkbench,
  exposure,
  exposureError,
  dashboard,
  jobs,
  layers
}: {
  onWorkbench: () => void;
  exposure: AdminExposure | null;
  exposureError: string;
  dashboard: WorkspaceDashboard | null;
  jobs: DownloadJob[];
  layers: ResultMapLayer[];
}) {
  return (
    <main className="pxr-app pxr-admin">
      <AdminHeader onWorkbench={onWorkbench} exposure={exposure} />
      <AdminSidebar />
      <section className="pxr-admin-content">
        <div className="pxr-admin-alert">
          <AlertTriangle size={23} />
          <strong>注意：请勿在未获得批准的情况下提高暴露比例。</strong>
          <span>{exposureError || '请遵循发布流程与变更管理策略。'}</span>
        </div>
        <AdminOpsDock exposure={exposure} dashboard={dashboard} jobs={jobs} />
        <RuntimeExposureSection exposure={exposure} />
        <GatesSection exposure={exposure} />
        <TrafficQualitySection dashboard={dashboard} jobs={jobs} layers={layers} />
        <RollbackSection exposure={exposure} />
      </section>
    </main>
  );
}

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>(() => (
    window.location.pathname.toLowerCase().includes('admin') ? 'admin' : 'workbench'
  ));
  const [user, setUser] = useState<CommercialUser | null>(null);
  const [chatContext, setChatContext] = useState<ChatContextPayload>({});
  const [currentSessionId, setCurrentSessionId] = useState('');
  const [consoleOpen, setConsoleOpen] = useState(viewMode === 'admin');
  const [chatOpen, setChatOpen] = useState(viewMode === 'workbench');
  const [toolsOpen, setToolsOpen] = useState(viewMode === 'workbench');
  const [resultLayerPalettePreferences] = useState<ResultLayerPalettePreferences>({});
  const [dashboard, setDashboard] = useState<WorkspaceDashboard | null>(null);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [resultLayers, setResultLayers] = useState<ResultMapLayer[]>([]);
  const [resultLayerState, setResultLayerState] = useState<ResultLayerStateMap>({});
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState('');
  const [adminExposure, setAdminExposure] = useState<AdminExposure | null>(null);
  const [adminExposureError, setAdminExposureError] = useState('');
  const [composerText, setComposerText] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState('');
  const [interactionMode, setInteractionMode] = useState<InteractionMode>('chat_only');
  const [interactionModeBusy, setInteractionModeBusy] = useState(false);
  const [interactionModeError, setInteractionModeError] = useState('');
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [authMode, setAuthMode] = useState<LoginMode>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [resultPanel] = useState<ResultPanel | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const streamingRef = useRef(false);
  const updateChatContext = (patch: Partial<ChatContextPayload>) => setChatContext((current) => mergeChatContext(current, patch));
  const mergeLayerStateForLegacyContract = (layers: ResultMapLayer[], current: ResultLayerStateMap) => (
    mergeResultLayerState(layers, current, resultLayerPalettePreferences)
  );
  void updateChatContext;
  void mergeLayerStateForLegacyContract;
  void consoleOpen;
  void chatOpen;
  void toolsOpen;

  const refreshAdminExposure = useCallback(async () => {
    if (!user?.user_id) {
      setAdminExposure(null);
      setAdminExposureError('未登录或无管理员上下文，管理员暴露接口显示只读空状态。');
      return;
    }
    try {
      const exposure = await fetchAdminExposure();
      setAdminExposure(exposure);
      setAdminExposureError('');
    } catch (err) {
      setAdminExposure(null);
      setAdminExposureError(err instanceof Error ? `管理员暴露接口读取失败：${err.message}` : '管理员暴露接口读取失败');
    }
  }, [user?.user_id]);

  const refreshWorkspace = useCallback(async () => {
    const userId = user?.user_id || '';
    if (!userId) {
      setDashboard(null);
      setJobs([]);
      setResultLayers([]);
      setMessages([]);
      setDashboardError('');
      setInteractionMode('chat_only');
      setInteractionModeError('');
      return;
    }
    setDashboardLoading(true);
    const sessionId = currentSessionId;
    const [dashboardResult, jobsResult, layersResult, sessionsResult] = await Promise.allSettled([
      api.dashboard(userId, sessionId),
      api.jobs(userId, sessionId),
      api.mapLayers(userId, sessionId),
      api.chatSessions(userId)
    ]);
    if (dashboardResult.status === 'fulfilled') {
      setDashboard(dashboardResult.value);
      setDashboardError('');
      if (!currentSessionId && dashboardResult.value.current_session_id) setCurrentSessionId(dashboardResult.value.current_session_id);
      if (!streamingRef.current && dashboardResult.value.messages?.length) setMessages(dashboardResult.value.messages);
    } else {
      setDashboardError(dashboardResult.reason instanceof Error ? dashboardResult.reason.message : '工作区读取失败');
    }
    if (jobsResult.status === 'fulfilled') setJobs(jobsResult.value.jobs || []);
    if (layersResult.status === 'fulfilled') setResultLayers(layersResult.value.layers || []);
    if (sessionsResult.status === 'fulfilled') {
      const nextSessionId = sessionsResult.value.current_session_id || currentSessionId;
      if (!currentSessionId && nextSessionId) setCurrentSessionId(nextSessionId);
      setInteractionMode(resolveInteractionMode(sessionsResult.value.sessions, nextSessionId));
      if (!streamingRef.current) setMessages(sessionsResult.value.messages || []);
    }
    setDashboardLoading(false);
  }, [currentSessionId, user?.user_id]);

  useEffect(() => {
    const saved = readStoredUser();
    if (saved) setUser(saved);
    let cancelled = false;
    api.me()
      .then((result) => {
        if (cancelled) return;
        if (result.authenticated && result.user) {
          setUser(result.user);
          writeStoredUser(result.user);
          return;
        }
        clearStoredAuth();
        setUser(null);
      })
      // Keep the locally restored user when the backend is temporarily unavailable.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) setCurrentSessionId('');
  }, [user]);

  useEffect(() => {
    refreshWorkspace().catch(() => undefined);
    const timer = window.setInterval(() => refreshWorkspace().catch(() => undefined), 8000);
    return () => window.clearInterval(timer);
  }, [refreshWorkspace]);

  useEffect(() => {
    refreshAdminExposure().catch(() => undefined);
    const timer = window.setInterval(() => refreshAdminExposure().catch(() => undefined), 15000);
    return () => window.clearInterval(timer);
  }, [refreshAdminExposure]);

  useEffect(() => {
    setResultLayerState((current) => mergeResultLayerState(resultLayers, current, resultLayerPalettePreferences));
  }, [resultLayers, resultLayerPalettePreferences]);

  const openLoginDialog = useCallback(() => {
    setAuthMode('login');
    setAuthError('');
    setAuthDialogOpen(true);
  }, []);

  const handleAuthSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const email = authEmail.trim();
    const password = authPassword;
    if (!email || !password) {
      setAuthError('请输入邮箱和密码。');
      return;
    }
    setAuthBusy(true);
    setAuthError('');
    try {
      const session = authMode === 'login' ? await api.login(email, password) : await api.register(email, password);
      writeStoredUser(session.user);
      setUser(session.user);
      setCurrentSessionId('');
      setMessages([]);
      setDashboardError('');
      setChatError('');
      setAuthPassword('');
      setAuthDialogOpen(false);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : '账号操作失败，请稍后重试。');
    } finally {
      setAuthBusy(false);
    }
  };

  const logoutUser = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Local logout should still clear the interface when the backend is unavailable.
    } finally {
      clearStoredAuth();
      setUser(null);
      setDashboard(null);
      setJobs([]);
      setResultLayers([]);
      setMessages([]);
      setCurrentSessionId('');
      setInteractionMode('chat_only');
      setInteractionModeError('');
      setChatError('');
    }
  }, []);

  const changeInteractionMode = useCallback(async (mode: InteractionMode) => {
    if (mode === interactionMode || interactionModeBusy) return;
    const userId = user?.user_id || '';
    if (!userId) {
      setInteractionModeError('请先登录后再切换聊天/执行模式。');
      openLoginDialog();
      return;
    }
    if (!currentSessionId) {
      setInteractionModeError('请先同步或创建会话后再切换模式。');
      return;
    }
    const previousMode = interactionMode;
    setInteractionMode(mode);
    setInteractionModeBusy(true);
    setInteractionModeError('');
    try {
      const response = await api.setChatInteractionMode(currentSessionId, mode, userId);
      setInteractionMode(response.interaction_mode);
      if (response.current_session_id && response.current_session_id !== currentSessionId) {
        setCurrentSessionId(response.current_session_id);
      }
      if (!streamingRef.current) setMessages(response.messages || []);
    } catch (err) {
      setInteractionMode(previousMode);
      setInteractionModeError(err instanceof Error ? err.message : '模式切换失败，请稍后重试。');
    } finally {
      setInteractionModeBusy(false);
    }
  }, [currentSessionId, interactionMode, interactionModeBusy, openLoginDialog, user?.user_id]);

  const applyRealtimeEvent = (event: RealtimeChatEvent) => {
    const content = event.delta || event.message || '';
    setMessages((current) => {
      const next = [...current];
      const last = next[next.length - 1];
      const meta = {
        ...(last?.meta || {}),
        task_id: event.task_id,
        job_id: event.job_id,
        status: event.status,
        progress: event.progress,
        phase: event.phase,
        current_step: event.current_step,
        management_view: event.management_view,
        presentation_result: event.presentation_result,
        streaming: event.kind === 'model_token'
      };
      if (last?.role === 'assistant' && last.meta?.streaming) {
        next[next.length - 1] = {
          ...last,
          content: event.kind === 'model_token' ? `${last.content || ''}${content}` : (content || last.content),
          meta
        };
        return next;
      }
      if (event.kind === 'model_token' || event.kind === 'model_complete' || content) {
        return [...next, { role: 'assistant', content, created_at: new Date().toISOString(), meta }];
      }
      return next;
    });
  };

  const sendPrompt = async (prompt: string) => {
    const text = prompt.trim();
    const userId = user?.user_id || '';
    if (!text) return;
    if (!userId) {
      setChatError('请先登录后再发送 GIS 任务。');
      return;
    }
    const taskId = `pxr_${Date.now()}`;
    setComposerText('');
    setChatError('');
    setChatSending(true);
    streamingRef.current = true;
    setMessages((current) => [
      ...current,
      { id: `${taskId}_user`, role: 'user', content: text, created_at: new Date().toISOString() },
      { id: `${taskId}_assistant`, role: 'assistant', content: '', created_at: new Date().toISOString(), meta: { streaming: true, task_id: taskId } }
    ]);
    try {
      await api.streamChat(text, userId, currentSessionId, chatContext, { onEvent: applyRealtimeEvent }, undefined, taskId);
      streamingRef.current = false;
      await refreshWorkspace();
    } catch (err) {
      setChatError(err instanceof Error ? err.message : '发送失败');
      setMessages((current) => [...current, { role: 'system', content: '发送失败，请稍后重试。', created_at: new Date().toISOString() }]);
    } finally {
      streamingRef.current = false;
      setChatSending(false);
      setMessages((current) => current.map((message) => message.meta?.task_id === taskId ? { ...message, meta: { ...(message.meta || {}), streaming: false } } : message));
    }
  };

  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const userId = user?.user_id || '';
    if (!userId) {
      setChatError('请先登录后再上传数据。');
      return;
    }
    setUploading(true);
    setChatError('');
    try {
      const response = await api.uploadFiles(files, userId, currentSessionId);
      setDashboard(response.dashboard);
      if (response.dashboard?.current_session_id && !currentSessionId) setCurrentSessionId(response.dashboard.current_session_id);
      if (response.messages?.length) {
        setMessages((current) => [...current, { role: 'system', content: response.messages.join('\n'), created_at: new Date().toISOString() }]);
      }
      await refreshWorkspace();
    } catch (err) {
      setChatError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const onToggleLayer = (layer: ResultMapLayer, index: number, visible: boolean) => {
    const key = resultLayerKey(layer, String(index));
    setResultLayerState((current) => ({
      ...current,
      [key]: {
        visible,
        removed: current[key]?.removed ?? false,
        palette: current[key]?.palette || 'cyan'
      }
    }));
  };

  const downloadArtifact = async (artifact: ArtifactView) => {
    try {
      if (artifact.artifactId) {
        await api.downloadArtifactById(artifact.artifactId, artifact.title, user?.user_id, currentSessionId);
        return;
      }
      if (artifact.downloadUrl) await api.downloadAuthenticated(artifact.downloadUrl, artifact.title);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : '下载失败');
    }
  };

  const setResultLayersFromMap = (layers: ResultMapLayer[]) => {
    setResultLayers(layers);
    setResultLayerState((current) => mergeResultLayerState(layers, current, resultLayerPalettePreferences));
  };

  const content = useMemo(() => {
    if (viewMode === 'admin') {
      return (
        <AdminView
          onWorkbench={() => {
            setViewMode('workbench');
            setConsoleOpen(false);
            setChatOpen(true);
            setToolsOpen(true);
          }}
          exposure={adminExposure}
          exposureError={adminExposureError}
          dashboard={dashboard}
          jobs={jobs}
          layers={resultLayers}
        />
      );
    }
    return (
      <WorkbenchView
        user={user}
        dashboard={dashboard}
        jobs={jobs}
        exposure={adminExposure}
        messages={messages}
        currentSessionId={currentSessionId}
        chatContext={chatContext}
        resultLayers={resultLayers}
        resultLayerState={resultLayerState}
        resultPanel={resultPanel}
        interactionMode={interactionMode}
        interactionModeBusy={interactionModeBusy}
        interactionModeError={interactionModeError}
        loading={dashboardLoading}
        error={dashboardError}
        composerText={composerText}
        sending={chatSending}
        uploading={uploading}
        chatError={chatError}
        fileInputRef={fileInputRef}
        onAdmin={() => {
          setViewMode('admin');
          setConsoleOpen(true);
          setChatOpen(false);
          setToolsOpen(false);
        }}
        onLogin={openLoginDialog}
        onLogout={logoutUser}
        onRefresh={() => refreshWorkspace().catch(() => undefined)}
        onUploadFiles={uploadFiles}
        onUploadClick={() => fileInputRef.current?.click()}
        onComposerText={setComposerText}
        onInteractionMode={changeInteractionMode}
        onSend={sendPrompt}
        onToggleLayer={onToggleLayer}
        onResultLayersChange={setResultLayersFromMap}
        onChatContextChange={updateChatContext}
        onDownloadArtifact={downloadArtifact}
      />
    );
  }, [
    adminExposure,
    adminExposureError,
    chatContext,
    chatError,
    chatSending,
    changeInteractionMode,
    composerText,
    currentSessionId,
    dashboard,
    dashboardError,
    dashboardLoading,
    interactionMode,
    interactionModeBusy,
    interactionModeError,
    jobs,
    messages,
    openLoginDialog,
    resultLayerState,
    resultLayers,
    logoutUser,
    uploading,
    user,
    viewMode
  ]);

  return (
    <>
      {content}
      <LoginDialog
        open={authDialogOpen}
        mode={authMode}
        email={authEmail}
        password={authPassword}
        busy={authBusy}
        error={authError}
        onClose={() => {
          if (!authBusy) setAuthDialogOpen(false);
        }}
        onMode={(mode) => {
          setAuthMode(mode);
          setAuthError('');
        }}
        onEmail={setAuthEmail}
        onPassword={setAuthPassword}
        onSubmit={handleAuthSubmit}
      />
      <LegacyIntegrationContract
        sessionId={currentSessionId}
        onSessionChange={setCurrentSessionId}
        chatContext={chatContext}
        onOpenMap={() => {
          setConsoleOpen(false);
          setChatOpen(true);
          setToolsOpen(true);
        }}
      />
    </>
  );
}
