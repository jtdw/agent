import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Check, ChevronsLeft, FileUp, Map as MapIcon, MessageSquare, Pencil, PlayCircle, Plus, RefreshCcw, SearchCheck, Sparkles, Trash2, UploadCloud, Wrench, X } from 'lucide-react';
import { api, ChatMessage, ChatModelState, ChatSession, CommercialUser, RealtimeChatEvent, ResultPanel, WorkspaceMention } from '@/lib/api';
import { GlassCard } from './GlassCard';
import { cn } from '@/lib/cn';
import { isLocalSecureContext } from './mapLayerPolicy';
import { parseMapTextCommand, type ParsedMapTextCommand } from './mapTextCommands';
import { assistantErrorContent, assistantReplyContent, normalizeChatMessages } from './chatMessageContent';
import type { ChatContextPayload } from '@/lib/chatContext';
import { ChatComposer } from './ChatComposer';
import { ChatMessageRenderer } from './ChatMessageRenderer';
import { UploadResultCard } from './UploadResultCard';
import { GSCloudAccountPanel } from './GSCloudAccountPanel';
import { ModalPortal } from './ModalPortal';

export type ExternalPromptCommand = { id: number; prompt: string };
type ChatWorkspaceMode = 'floating' | 'page';
export type ChatWorkspaceProps = {
  user: CommercialUser | null;
  setUser: (u: CommercialUser | null) => void;
  onClose?: () => void;
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  externalPrompt?: ExternalPromptCommand | null;
  onResultPanel?: (panel: ResultPanel) => void;
  onSessionChange?: (sessionId: string) => void;
  chatContext?: ChatContextPayload;
  mentionDatasets?: Array<Record<string, unknown> | WorkspaceMention>;
  mode?: ChatWorkspaceMode;
};

const EMPTY_MENTION_DATASETS: Array<Record<string, unknown> | WorkspaceMention> = [];

function normalizeWorkspaceMentions(items: Array<Record<string, unknown> | WorkspaceMention> = []): WorkspaceMention[] {
  return items.flatMap((item) => {
    const raw = item as Record<string, unknown>;
    const name = String(raw.name || '').trim();
    if (!name) return [];
    const meta = raw.meta && typeof raw.meta === 'object' ? raw.meta as Record<string, unknown> : {};
    const columns = Array.isArray(meta.columns) ? meta.columns : [];
    const path = String(raw.path || raw.filename || '');
    return [{
      id: String(raw.id || name),
      name,
      mention: String(raw.mention || `@{${name}}`),
      type: String(raw.type || raw.data_type || 'file'),
      filename: String(raw.filename || path.split(/[\\/]/).pop() || name),
      row_count: Number.isFinite(Number(raw.row_count ?? meta.rows)) ? Number(raw.row_count ?? meta.rows) : null,
      column_count: Number.isFinite(Number(raw.column_count)) ? Number(raw.column_count) : columns.length || null,
      crs: String(raw.crs || meta.crs || '')
    }];
  });
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-1">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-2 w-2 rounded-full bg-cyan-glow" animate={{ y: [0, -5, 0], opacity: [0.45, 1, 0.45] }} transition={{ duration: 0.75, repeat: Infinity, delay: i * 0.12 }} />
      ))}
    </div>
  );
}

function ThinkingStatusCard({ mode }: { mode: 'chat_only' | 'tool_enabled' }) {
  const steps = mode === 'tool_enabled'
    ? ['理解目标', '生成计划', '等待校验']
    : ['理解问题', '检索知识', '组织回答'];
  return (
    <div data-testid="chat-thinking-status" className="w-full max-w-[min(88%,32rem)] rounded-[22px] border border-slate-200/80 bg-white/84 px-4 py-3 shadow-[0_14px_34px_rgba(15,23,42,.08)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/68">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-black text-slate-900 dark:text-slate-100">{mode === 'tool_enabled' ? '正在准备工具任务' : '正在组织回答'}</div>
          <div className="mt-1 text-[11px] font-semibold text-slate-500 dark:text-slate-400">{mode === 'tool_enabled' ? '如需执行，会先生成计划并完成校验。' : '聊天模式不会创建任务或操作数据。'}</div>
        </div>
        <ThinkingDots />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {steps.map((step, index) => (
          <span key={step} className={cn('rounded-full px-2 py-1 text-[11px] font-black', index === 0 ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300')}>
            {step}
          </span>
        ))}
      </div>
    </div>
  );
}

function RealtimeSyncIndicator({ state }: { state: 'connecting' | 'live' | 'polling' }) {
  const label = state === 'live' ? '实时同步' : state === 'connecting' ? '正在连接' : '定时同步';
  const tone = state === 'live'
    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200'
    : state === 'connecting'
      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200'
      : 'bg-amber-50 text-amber-700 dark:bg-amber-950/35 dark:text-amber-200';
  return <span data-testid="realtime-sync-indicator" className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-black', tone)}>{label}</span>;
}

const PROMPT_GROUPS = [
  {
    title: '检查工作区数据',
    description: '识别字段、坐标、时间与缺失值',
    icon: SearchCheck,
    prompt: '检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。'
  },
  {
    title: '开始融合建模',
    description: '按论文流程准备模型与验证',
    icon: Sparkles,
    prompt: '按照闪电河流域土壤水分融合论文流程，检查能否做 BTCH、RF、XGBoost、LSTM 与 GCP。'
  },
  {
    title: '创建地图',
    description: '从现有图层生成制图方案',
    icon: MapIcon,
    prompt: '概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。'
  },
  {
    title: '准备下载数据',
    description: '查找 DEM、遥感或土壤水分数据',
    icon: UploadCloud,
    prompt: '根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。'
  }
];

const QUICK_PROMPTS = PROMPT_GROUPS.map((group) => group.prompt);

function sessionDate(session: ChatSession) {
  const value = session.updated_at || session.created_at;
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date);
}

function MessageSourceBadge({ message }: { message: ChatMessage }) {
  const model = String(message.meta?.model || '');
  const reason = String(message.meta?.reason || '');
  if (!model && !reason) return null;
  const label = reason === 'error' ? '错误提示' : model === 'builtin-workspace' ? '本地工作区' : model || '智能体';
  return (
    <div className={cn('mb-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-black', reason === 'error' ? 'bg-coral/10 text-coral' : 'bg-cyan-glow/10 text-ocean dark:text-cyan-glow')}>
      {reason === 'error' ? <AlertTriangle size={12} /> : <Sparkles size={12} />}
      {label}
    </div>
  );
}

function renderInlineMarkdown(text: string) {
  let offset = 0;
  return String(text || '').split(/(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*)/g).map((part) => {
    const bold = part.match(/^\*{2,3}(.+)\*{2,3}$/);
    const key = `inline-${offset}-${hashString(part)}`;
    offset += part.length;
    return bold ? <strong key={key} className="font-black text-inherit">{bold[1]}</strong> : <span key={key}>{part}</span>;
  });
}

function hashString(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function messageKey(message: ChatMessage) {
  if (message.id) return `message-${message.id}`;
  if (message.message_id) return `message-${message.message_id}`;
  const stableParts = [message.role, message.created_at || '', message.session_id || '', String(message.content || '').length, hashString(message.content || '')];
  return `message-${stableParts.join('-')}`;
}

function messageIsToolTask(message: ChatMessage) {
  const meta = message.meta || {};
  const mode = String(meta.mode || '');
  const actionType = String(meta.action_required?.type || '');
  const interactionType = String(meta.interaction_type || '');
  const reason = String(meta.reason || '');
  return reason !== 'tool_mode_required' && (
    interactionType === 'tool_task'
    || Boolean(meta.task_card)
    || Boolean(meta.management_view)
    || Boolean(meta.download_management_view)
    || ['background_worker', 'validated_download_executor', 'coordinated_workflow', 'validated_workflow_executor', 'validated_tool_executor'].includes(mode)
    || ['confirmation_required', 'login_required'].includes(actionType)
  );
}

function responseAssistantMessage(response: {
  reply?: string;
  model?: string;
  reason?: string;
  artifacts?: unknown;
  files?: unknown;
  presentation_result?: unknown;
  execution_summary?: unknown;
  user_facing_result?: unknown;
  management_view?: unknown;
  download_management_view?: unknown;
  task_card?: unknown;
  confirmed_pending_confirmation_id?: unknown;
  [key: string]: unknown;
}): ChatMessage {
  const meta: Record<string, unknown> = {
    model: response.model,
    reason: response.reason,
    artifacts: response.artifacts || response.files || [],
    presentation_result: response.presentation_result,
    execution_summary: response.execution_summary,
    user_facing_result: response.user_facing_result,
  };
  ['management_view', 'download_management_view', 'task_card', 'confirmed_pending_confirmation_id', 'interaction_type', 'mode', 'status'].forEach((key) => {
    if (response[key] !== undefined) meta[key] = response[key];
  });
  return { role: 'assistant', content: assistantReplyContent(response.reply), meta };
}

function messageMatchesConfirmation(message: ChatMessage, confirmationId: string) {
  const token = confirmationId.trim();
  if (!token || message.role !== 'assistant') return false;
  const meta = message.meta || {};
  const action = (meta.action_required || {}) as Record<string, unknown>;
  return String(action.confirmed_action_id || '') === token
    || String(meta.confirmed_pending_confirmation_id || '') === token
    || String(meta.confirmation_id || '') === token;
}

function taskIdsFromMessage(message: ChatMessage) {
  const meta = message.meta || {};
  const action = (meta.action_required || {}) as Record<string, unknown>;
  const managementView = (meta.management_view || meta.download_management_view || {}) as Record<string, unknown>;
  const card = (meta.task_card || {}) as Record<string, unknown>;
  return new Set(
    [
      action.job_id,
      managementView.task_id,
      managementView.job_id,
      card.task_id,
      meta.job_id,
      meta.task_id,
    ]
      .map((value) => String(value || '').trim())
      .filter(Boolean)
  );
}

function messageMatchesJob(message: ChatMessage, jobId: string) {
  const target = jobId.trim();
  if (!target || message.role !== 'assistant') return false;
  return taskIdsFromMessage(message).has(target);
}

function messageMatchesRealtimeEvent(message: ChatMessage, event: RealtimeChatEvent) {
  if (message.role !== 'assistant') return false;
  const taskId = String(event.task_id || '').trim();
  const jobId = String(event.job_id || '').trim();
  const ids = taskIdsFromMessage(message);
  return Boolean((taskId && ids.has(taskId)) || (jobId && ids.has(jobId)));
}

function mergeTaskCardUpdate(
  current: ChatMessage[],
  matcher: (message: ChatMessage) => boolean,
  update: ChatMessage,
  options: { consumeAction?: boolean } = {}
) {
  let matched = false;
  const next = [...current];
  for (let index = next.length - 1; index >= 0; index -= 1) {
    const existing = next[index];
    if (!matcher(existing)) continue;
    matched = true;
    const mergedMeta = { ...(existing.meta || {}), ...(update.meta || {}) } as NonNullable<ChatMessage['meta']>;
    if (options.consumeAction) delete mergedMeta.action_required;
    next[index] = {
      ...existing,
      content: update.content || existing.content,
      meta: mergedMeta,
    };
    break;
  }
  return matched ? next : [...current, update];
}

function messageSignature(message: ChatMessage) {
  return `${message.role}|${String(message.content || '')}`;
}

function mergeStableClientMessageIds(current: ChatMessage[], incoming: ChatMessage[]) {
  const clientIds = new Map<string, string[]>();
  current.forEach((message) => {
    if (!message.id) return;
    const signature = messageSignature(message);
    const bucket = clientIds.get(signature) || [];
    bucket.push(message.id);
    clientIds.set(signature, bucket);
  });
  return incoming.map((message) => {
    if (message.id) return message;
    const bucket = clientIds.get(messageSignature(message));
    const id = bucket?.shift();
    return id ? { ...message, id } : message;
  });
}

function mergeServerMessages(current: ChatMessage[], incoming: ChatMessage[]) {
  if (!incoming.length && current.length > 0) return current;
  return mergeStableClientMessageIds(current, incoming);
}

function MarkdownMessage({ content }: { content: string }) {
  const lines = String(content || '').split(/\r?\n/);
  let offset = 0;
  return (
    <div className="chat-markdown">
      {lines.map((line) => {
        const key = `line-${offset}-${hashString(line)}`;
        offset += line.length + 1;
        const trimmed = line.trim();
        if (!trimmed) return <div key={key} className="h-2" />;
        const heading = trimmed.match(/^#{1,6}\s+(.+)$/);
        if (heading) return <div key={key} className="chat-md-heading">{renderInlineMarkdown(heading[1])}</div>;
        if (/^\*{3,}$/.test(trimmed) || /^-{3,}$/.test(trimmed)) return <div key={key} className="chat-md-rule" />;
        const bullet = trimmed.match(/^[-*]\s+(.+)$/);
        if (bullet) return <div key={key} className="chat-md-list"><span>•</span><span>{renderInlineMarkdown(bullet[1])}</span></div>;
        const numbered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
        if (numbered) return <div key={key} className="chat-md-list"><span>{numbered[1]}.</span><span>{renderInlineMarkdown(numbered[2])}</span></div>;
        return <div key={key}>{renderInlineMarkdown(line)}</div>;
      })}
    </div>
  );
}

export function ChatWorkspace({
  user,
  onClose,
  onMapTextCommand,
  externalPrompt,
  onResultPanel,
  onSessionChange,
  chatContext = {},
  mentionDatasets = EMPTY_MENTION_DATASETS,
  mode = 'floating'
}: ChatWorkspaceProps) {
  const [width, setWidth] = useState(430);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState('');
  const [thinking, setThinking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [lastFailedPrompt, setLastFailedPrompt] = useState('');
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceUnavailableReason, setVoiceUnavailableReason] = useState('');
  const [chatModels, setChatModels] = useState<ChatModelState | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const visibleSessions = useMemo(() => {
    const byId = new Map<string, ChatSession>();
    sessions.forEach((session) => {
      const id = String(session.session_id || '').trim();
      if (id) byId.set(id, session);
    });
    return Array.from(byId.values());
  }, [sessions]);
  const visibleModels = useMemo(() => {
    const byId = new Map<string, NonNullable<ChatModelState['models']>[number]>();
    (chatModels?.models || []).forEach((model) => {
      const id = String(model.id || '').trim();
      if (id) byId.set(id, model);
    });
    return Array.from(byId.values());
  }, [chatModels?.models]);
  const currentInteractionMode = useMemo<'chat_only' | 'tool_enabled'>(() => {
    const session = visibleSessions.find((item) => item.session_id === currentSessionId);
    return session?.interaction_mode === 'tool_enabled' ? 'tool_enabled' : 'chat_only';
  }, [currentSessionId, visibleSessions]);
  const interactionModeLabel = currentInteractionMode === 'tool_enabled'
    ? '工具模式：可以在确认和校验后执行下载、GIS 处理和建模。'
    : '聊天模式：只回答问题，不会操作数据或创建任务。';
  const renderMessages = useMemo(() => {
    const byKey = new Map<string, ChatMessage>();
    messages.forEach((message) => {
      byKey.set(messageKey(message), message);
    });
    return Array.from(byKey.values());
  }, [messages]);
  const [modelNotice, setModelNotice] = useState('');
  const [modelError, setModelError] = useState('');
  const [workspaceMentions, setWorkspaceMentions] = useState<WorkspaceMention[]>(() => normalizeWorkspaceMentions(mentionDatasets));
  const [gscloudLoginOpen, setGSCloudLoginOpen] = useState(false);
  const [pendingLoginJobId, setPendingLoginJobId] = useState('');
  const [resumeReadyJobIds, setResumeReadyJobIds] = useState<Set<string>>(() => new Set());
  const [realtimeSyncState, setRealtimeSyncState] = useState<'connecting' | 'live' | 'polling'>('polling');
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<unknown>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeTaskIdRef = useRef<string>('');
  const stickToBottomRef = useRef(true);
  const handledLoginMessageRef = useRef('');
  const announcedDownloadJobsRef = useRef<Set<string>>(new Set());
  const sessionRefreshSeqRef = useRef(0);
  const lastKnownUserIdRef = useRef('');
  const lastSuccessfulSessionUserIdRef = useRef('');
  const latestUserIdRef = useRef('');
  const mountedRef = useRef(true);
  const realtimeEventSourceRef = useRef<EventSource | null>(null);
  const realtimeEventIdsRef = useRef<Set<string>>(new Set());
  const realtimeTaskVersionRef = useRef(0);
  const userId = user?.user_id || '';
  latestUserIdRef.current = userId;

  function applyRealtimeEvent(event: RealtimeChatEvent) {
    const eventId = String(event.event_id || '').trim();
    if (!eventId || realtimeEventIdsRef.current.has(eventId)) return;
    realtimeEventIdsRef.current.add(eventId);
    if (realtimeEventIdsRef.current.size > 800) {
      realtimeEventIdsRef.current = new Set(Array.from(realtimeEventIdsRef.current).slice(-400));
    }
    const version = Number(event.version || 0);
    if (version > 0 && version < 1_000_000_000) {
      if (version <= realtimeTaskVersionRef.current) return;
      realtimeTaskVersionRef.current = version;
    }
    const taskUpdate = event.task_update && typeof event.task_update === 'object' ? event.task_update : {};
    const meta: Record<string, unknown> = {
      task_id: event.task_id || '',
      job_id: event.job_id || '',
      status: event.status || '',
      realtime_sync: realtimeSyncState,
      streaming: event.kind === 'model_token',
      ...taskUpdate,
    };
    if (event.management_view) meta.management_view = event.management_view;
    if (event.presentation_result) meta.presentation_result = event.presentation_result;
    const content = event.kind === 'model_token'
      ? event.delta || ''
      : event.kind === 'model_complete'
        ? event.delta || ''
        : event.message || '';
    setMessages((current) => {
      const next = [...current];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        const existing = next[index];
        if (!messageMatchesRealtimeEvent(existing, event)) continue;
        next[index] = {
          ...existing,
          content: event.kind === 'model_token' ? `${existing.content || ''}${content}` : (content || existing.content),
          meta: { ...(existing.meta || {}), ...meta, streaming: event.kind === 'model_token' },
        };
        return next;
      }
      return current;
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    realtimeEventSourceRef.current?.close();
    realtimeEventSourceRef.current = null;
    realtimeEventIdsRef.current = new Set();
    realtimeTaskVersionRef.current = 0;
    if (!userId || !currentSessionId) {
      setRealtimeSyncState('polling');
      return;
    }
    let disposed = false;
    setRealtimeSyncState('connecting');
    const receive = (event: RealtimeChatEvent) => {
      if (!disposed) applyRealtimeEvent(event);
    };
    api.replayChatEvents(userId, currentSessionId, 0)
      .then((result) => result.events.forEach(receive))
      .catch(() => {
        if (!disposed) setRealtimeSyncState('polling');
      });
    const source = api.openChatEventStream(userId, currentSessionId, 0);
    realtimeEventSourceRef.current = source;
    const eventTypes: RealtimeChatEvent['kind'][] = ['task_status', 'task_progress', 'task_result', 'model_token', 'model_complete', 'warning', 'error'];
    const handle = (raw: MessageEvent<string>) => {
      try {
        receive(JSON.parse(raw.data) as RealtimeChatEvent);
      } catch {}
    };
    eventTypes.forEach((type) => source.addEventListener(type, handle as EventListener));
    source.onopen = () => {
      if (!disposed) setRealtimeSyncState('live');
    };
    source.onerror = () => {
      if (!disposed) setRealtimeSyncState('polling');
    };
    return () => {
      disposed = true;
      eventTypes.forEach((type) => source.removeEventListener(type, handle as EventListener));
      source.close();
      if (realtimeEventSourceRef.current === source) realtimeEventSourceRef.current = null;
    };
  }, [userId, currentSessionId]);

  const refreshSessions = async () => {
    const requestedUserId = userId;
    const seq = ++sessionRefreshSeqRef.current;
    if (!userId) {
      if (lastKnownUserIdRef.current) {
        lastKnownUserIdRef.current = '';
        lastSuccessfulSessionUserIdRef.current = '';
        setSessions([]);
        setCurrentSessionId('');
        onSessionChange?.('');
        setMessages([]);
        return;
      }
    }
    if (requestedUserId) lastKnownUserIdRef.current = requestedUserId;
    let r = await api.chatSessions(requestedUserId);
    if ((!r.sessions || r.sessions.length === 0) && r.current_session_id) {
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      if (seq === sessionRefreshSeqRef.current && latestUserIdRef.current === requestedUserId) {
        const retry = await api.chatSessions(requestedUserId);
        if ((retry.sessions || []).length > 0) r = retry;
      }
    }
    if (seq !== sessionRefreshSeqRef.current || latestUserIdRef.current !== requestedUserId) return;
    const nextSessions = (r.sessions || []).length > 0
      ? r.sessions || []
      : r.current_session_id
        ? [{ session_id: r.current_session_id, title: '新对话' }]
        : [];
    if (requestedUserId && nextSessions.length === 0 && lastSuccessfulSessionUserIdRef.current === requestedUserId) {
      return;
    }
    setSessions(nextSessions);
    if (nextSessions.length > 0) lastSuccessfulSessionUserIdRef.current = requestedUserId;
    setCurrentSessionId(r.current_session_id || '');
    onSessionChange?.(r.current_session_id || '');
    setMessages((current) => mergeServerMessages(current, normalizeChatMessages(r.messages)));
  };

  useEffect(() => {
    refreshSessions().catch(() => {
      setError('聊天记录加载失败，已保留当前显示内容，可稍后重试。');
      setMessages((current) => current.length ? [...current, { role: 'system', content: '聊天记录暂时无法刷新，已保留当前显示内容。', meta: { reason: 'chat_load_failed' } }] : current);
    });
  }, [userId]);

  useEffect(() => {
    const message = [...messages].reverse().find((item) => item.meta?.action_required?.type === 'login_required');
    const jobId = String(message?.meta?.action_required?.job_id || '');
    const key = message ? `${messageKey(message)}:${jobId}` : '';
    if (!message || !jobId || handledLoginMessageRef.current === key || resumeReadyJobIds.has(jobId)) return;
    handledLoginMessageRef.current = key;
    setPendingLoginJobId(jobId);
    setGSCloudLoginOpen(true);
  }, [messages, resumeReadyJobIds]);

  const openGSCloudLogin = (jobId: string) => {
    setPendingLoginJobId(jobId);
    setGSCloudLoginOpen(true);
  };

  const markGSCloudLoginComplete = (jobId: string) => {
    if (jobId) setResumeReadyJobIds((current) => new Set(current).add(jobId));
    setGSCloudLoginOpen(false);
  };

  const watchDownloadJob = async (jobId: string) => {
    for (let attempt = 0; attempt < 450; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      if (!mountedRef.current) return;
      try {
        const result = await api.jobs(userId, currentSessionId);
        const view = result.management_views?.find((item) => item.task_id === jobId);
        const job = (result.jobs || []).find((item) => item.job_id === jobId);
        const status = view?.status || job?.status || '';
        if (!job && !view) continue;
        if ((status === 'completed' || status === 'success' || status === 'succeeded') && !announcedDownloadJobsRef.current.has(jobId)) {
          announcedDownloadJobsRef.current.add(jobId);
          const artifactRefs = view?.artifact_refs || job?.artifacts || [];
          const summary = view?.user_message || '下载完成。结果文件已注册，可以直接下载。';
          setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
            role: 'assistant',
            content: summary,
            meta: {
              artifacts: artifactRefs,
              reason: 'download_success',
              interaction_type: 'tool_task',
              management_view: view,
              presentation_result: {
                schema_version: 'presentation-result/v1',
                status: 'succeeded',
                concise_summary: summary,
                artifact_refs: artifactRefs,
                map_layer_refs: view?.map_layer_refs || [],
                warnings: view?.warnings || [],
                next_action_suggestions: view?.available_actions?.includes('view_artifacts') ? ['查看或下载结果文件'] : [],
              },
              execution_summary: {
                schema_version: 'execution-summary/v1',
                status: 'succeeded',
                summary,
                artifact_count: Array.isArray(artifactRefs) ? artifactRefs.length : 0,
              },
            }
          }));
          return;
        }
        if (status === 'failed' || status === 'canceled' || status === 'cancelled') {
          const failedStatus = status === 'canceled' || status === 'cancelled' ? 'cancelled' : 'failed';
          const summary = view?.user_message || view?.error_title || '任务失败或已取消。';
          setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
            role: 'assistant',
            content: summary,
            meta: {
              reason: 'download_failed',
              interaction_type: 'tool_task',
              management_view: view,
              presentation_result: {
                schema_version: 'presentation-result/v1',
                status: failedStatus,
                concise_summary: view?.display_title || '下载任务',
                artifact_refs: [],
                warnings: view?.warnings || [],
                error_summary: summary,
                next_action_suggestions: view?.available_actions?.includes('retry') ? ['重试任务'] : [],
              },
              execution_summary: {
                schema_version: 'execution-summary/v1',
                status: failedStatus,
                summary,
              },
            }
          }));
          return;
        }
      } catch {
        // Keep polling through transient API failures.
      }
    }
  };

  const resumeDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      const result = await api.resumeDownloadJob(jobId);
      const content = result.auto_started
        ? '已恢复当前下载任务，任务正在运行。完成后会在对话中显示下载文件。'
        : result.reason === 'clarification_required'
          ? '任务仍缺少下载参数，请先补充范围或其他必要参数。'
          : '任务尚未恢复，请检查登录状态。';
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content,
        meta: {
          reason: result.reason || 'download_resume',
          interaction_type: 'tool_task',
          management_view: result.management_view,
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: result.auto_started ? 'running' : 'awaiting_confirmation',
            concise_summary: content,
            artifact_refs: [],
            warnings: [],
            next_action_suggestions: result.auto_started ? [] : ['检查登录状态后继续'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: result.auto_started ? 'running' : 'awaiting_confirmation',
            summary: content,
          },
        }
      }));
      if (result.auto_started) void watchDownloadJob(jobId);
      setResumeReadyJobIds((current) => {
        const next = new Set(current);
        next.delete(jobId);
        return next;
      });
    } catch (cause) {
      setMessages((current) => [...current, { role: 'assistant', content: assistantErrorContent(cause), meta: { reason: 'error' } }]);
    }
  };

  const cancelDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      await api.cancelDownloadJob(jobId, userId, '用户在登录引导中取消任务。', currentSessionId);
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content: '下载任务已取消。',
        meta: {
          reason: 'download_cancelled',
          interaction_type: 'tool_task',
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: 'cancelled',
            concise_summary: '下载任务已取消。',
            artifact_refs: [],
            warnings: [],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: 'cancelled',
            summary: '下载任务已取消。',
          },
        }
      }));
      setGSCloudLoginOpen(false);
    } catch (cause) {
      setMessages((current) => [...current, { role: 'assistant', content: assistantErrorContent(cause), meta: { reason: 'error' } }]);
    }
  };

  const retryDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      const result = await api.retryDownloadJob(jobId, userId, currentSessionId);
      const retryJobId = String(result.management_view?.task_id || result.job?.job_id || '');
      const targetJobId = retryJobId || jobId;
      const status = String(result.management_view?.status || result.job?.status || (result.auto_started ? 'running' : 'queued'));
      const content = result.auto_started
        ? '已创建重试任务并开始后台下载。'
        : result.reason === 'login_required'
          ? '已创建重试任务，但需要先完成数据源登录。'
          : '已创建重试任务，等待后台调度。';
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content,
        meta: {
          reason: 'download_retry',
          interaction_type: 'tool_task',
          management_view: result.management_view,
          action_required: status === 'waiting_login' ? { type: 'login_required', job_id: targetJobId } : undefined,
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: status === 'waiting_login' ? 'waiting_login' : status === 'failed' ? 'failed' : 'running',
            concise_summary: content,
            artifact_refs: [],
            warnings: [],
            next_action_suggestions: status === 'waiting_login' ? ['完成登录后继续下载'] : ['等待任务完成'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status,
            summary: content,
          },
        }
      }));
      if (targetJobId && status !== 'waiting_login') void watchDownloadJob(targetJobId);
    } catch (cause) {
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content: assistantErrorContent(cause),
        meta: {
          reason: 'download_retry_failed',
          interaction_type: 'tool_task',
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: 'failed',
            concise_summary: '重试任务失败。',
            artifact_refs: [],
            warnings: [],
            error_summary: assistantErrorContent(cause),
            next_action_suggestions: ['检查任务状态或稍后重试'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: 'failed',
            summary: '重试任务失败。',
          },
        }
      }));
    }
  };

  const chooseClarification = (value: string, label: string) => {
    if (value === 'upload_boundary') {
      fileInputRef.current?.click();
      return;
    }
    if (value === 'active_region') {
      sendPrompt('帮我下载当前研究区的 DEM，使用默认 30m GeoTIFF 并裁剪到研究区。');
      return;
    }
    setInput(value === 'admin_region' ? '下载行政区：' : '下载 bbox：');
    setError(`请补充${label}后发送。`);
  };

  useEffect(() => {
    setWorkspaceMentions(normalizeWorkspaceMentions(mentionDatasets));
  }, [mentionDatasets]);

  useEffect(() => {
    if (!userId) {
      setWorkspaceMentions([]);
      return;
    }
    api.workspaceMentions(userId, currentSessionId)
      .then((result) => setWorkspaceMentions(normalizeWorkspaceMentions(result.items || [])))
      .catch(() => {});
  }, [userId, currentSessionId]);

  useEffect(() => {
    setModelNotice('');
    setModelError('');
    if (!userId || !currentSessionId) {
      setChatModels(null);
      return;
    }
    let active = true;
    setModelLoading(true);
    api.chatModels(userId, currentSessionId)
      .then((result) => { if (active) setChatModels(result); })
      .catch((cause) => { if (active) setModelError(cause instanceof Error ? cause.message : '模型列表加载失败'); })
      .finally(() => { if (active) setModelLoading(false); });
    return () => { active = false; };
  }, [userId, currentSessionId]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, thinking]);

  useEffect(() => {
    if (!isLocalSecureContext(window.location.protocol, window.location.hostname)) {
      setVoiceSupported(false);
      setVoiceUnavailableReason('浏览器只允许 HTTPS、localhost 或 127.0.0.1 页面使用麦克风。请用 http://127.0.0.1:5173 打开，或部署 HTTPS。');
      return;
    }
    const SpeechRecognition = (window as unknown as { SpeechRecognition?: new () => unknown; webkitSpeechRecognition?: new () => unknown }).SpeechRecognition
      || (window as unknown as { webkitSpeechRecognition?: new () => unknown }).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceSupported(false);
      setVoiceUnavailableReason('当前浏览器不支持语音识别。请使用 Chrome 或 Edge，并允许麦克风权限。');
      return;
    }
    const recognition = new SpeechRecognition() as {
      lang: string;
      continuous: boolean;
      interimResults: boolean;
      start: () => void;
      stop: () => void;
      onresult: ((event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
      onerror: (() => void) | null;
      onend: (() => void) | null;
    };
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      for (let i = 0; i < event.results.length; i += 1) {
        const text = event.results[i][0]?.transcript || '';
        if (event.results[i].isFinal) finalText += text;
        else interimText += text;
      }
      const text = (finalText || interimText).trim();
      if (text) setInput(text);
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    return () => recognition.stop();
  }, []);

  const appendSystem = (content: string) => setMessages((v) => [...v, { role: 'system', content }]);

  const changeChatModel = async (model: string) => {
    if (!userId || !currentSessionId || modelLoading) return;
    const previous = chatModels;
    setModelLoading(true);
    setModelNotice('');
    setModelError('');
    try {
      const result = await api.selectChatModel(model, userId, currentSessionId);
      setChatModels(result);
      setModelNotice('已切换');
      window.setTimeout(() => setModelNotice(''), 1800);
    } catch (cause) {
      setChatModels(previous);
      setModelError(cause instanceof Error ? cause.message : '模型切换失败');
    } finally {
      setModelLoading(false);
    }
  };

  const sendPrompt = async (prompt: string) => {
    const text = prompt.trim();
    if (!text || thinking) return;
    if (!userId) {
      setError('请先登录账号，再使用智能助手对话。');
      return;
    }
    setInput('');
    setError('');
    const mapCommand = parseMapTextCommand(text);
    if (mapCommand && onMapTextCommand) {
      const reply = onMapTextCommand(mapCommand);
      setMessages((v) => [...v, { role: 'user', content: text }, { role: 'assistant', content: reply || '地图操作已完成。' }]);
      return;
    }
    const optimisticUserMessage: ChatMessage = { id: `pending-${Date.now()}-${hashString(text)}`, role: 'user', content: text };
    setThinking(true);
    const controller = new AbortController();
    const taskId = `chat_${Date.now()}_${hashString(text)}`;
    const streamingAssistantMessage: ChatMessage = {
      id: `stream-${taskId}`,
      role: 'assistant',
      content: '',
      meta: {
        task_id: taskId,
        status: 'planning',
        streaming: true,
        realtime_sync: realtimeSyncState,
      }
    };
    setMessages((v) => [...v, optimisticUserMessage, streamingAssistantMessage]);
    abortRef.current = controller;
    activeTaskIdRef.current = taskId;
    try {
      await api.streamChat(
        text,
        userId,
        currentSessionId,
        { ...chatContext, session_id: currentSessionId },
        { onEvent: applyRealtimeEvent },
        controller.signal,
        taskId,
      );
      setLastFailedPrompt('');
      refreshSessions().catch(() => {});
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      const content = assistantErrorContent(e);
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, taskId), {
        role: 'assistant',
        content,
        meta: { task_id: taskId, reason: 'error', status: 'failed', streaming: false },
      }));
      setLastFailedPrompt(text);
      setError('');
    } finally {
      setThinking(false);
      if (abortRef.current === controller) abortRef.current = null;
      if (activeTaskIdRef.current === taskId) activeTaskIdRef.current = '';
    }
  };

  const confirmAction = async (confirmationPrompt: string, confirmedActionId: string) => {
    const prompt = confirmationPrompt.trim();
    const token = confirmedActionId.trim();
    if (!token || thinking) return;
    if (!userId) {
      setError('请先登录账号，再确认执行。');
      return;
    }
    setError('');
    setThinking(true);
    const controller = new AbortController();
    const taskId = `chat_confirm_${Date.now()}_${hashString(token)}`;
    abortRef.current = controller;
    activeTaskIdRef.current = taskId;
    try {
      const r = await api.confirmChatAction(token, prompt || '确认执行', userId, currentSessionId, { ...chatContext, session_id: currentSessionId }, controller.signal, taskId);
      if (r.messages) {
        const incoming = normalizeChatMessages(r.messages);
        const updated = incoming.find((message) => message.role === 'assistant' && messageMatchesConfirmation(message, token))
          || [...incoming].reverse().find((message) => message.role === 'assistant' && messageIsToolTask(message));
        setMessages((current) => updated
          ? mergeTaskCardUpdate(current, (message) => messageMatchesConfirmation(message, token), updated, { consumeAction: true })
          : mergeServerMessages(current, incoming));
      } else {
        setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesConfirmation(message, token), responseAssistantMessage(r), { consumeAction: true }));
      }
      if (r.sessions) setSessions(r.sessions);
      if (r.result_panel) onResultPanel?.(r.result_panel);
      const nextSessionId = r.current_session_id || currentSessionId;
      setCurrentSessionId(nextSessionId);
      onSessionChange?.(nextSessionId);
      setLastFailedPrompt('');
      refreshSessions().catch(() => {});
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      const content = assistantErrorContent(e);
      setMessages((v) => [...v, { role: 'assistant', content, meta: { reason: 'error' } }]);
      setError('');
    } finally {
      setThinking(false);
      if (abortRef.current === controller) abortRef.current = null;
      if (activeTaskIdRef.current === taskId) activeTaskIdRef.current = '';
    }
  };

  const send = () => sendPrompt(input);
  const stopCurrentRequest = () => {
    const taskId = activeTaskIdRef.current;
    if (taskId) api.cancelChatTask(taskId, userId, '用户点击停止。').catch(() => {});
    abortRef.current?.abort();
    abortRef.current = null;
    activeTaskIdRef.current = '';
    setThinking(false);
  };

  useEffect(() => {
    if (externalPrompt?.prompt) sendPrompt(externalPrompt.prompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalPrompt?.id]);

  const toggleVoice = () => {
    if (!voiceSupported) {
      setError(voiceUnavailableReason || '当前浏览器不支持语音识别。请使用 Chrome 或 Edge，并允许麦克风权限。');
      return;
    }
    const recognition = recognitionRef.current as { start: () => void; stop: () => void } | null;
    if (!recognition) return;
    try {
      if (listening) {
        recognition.stop();
        setListening(false);
      } else {
        setError('');
        recognition.start();
        setListening(true);
      }
    } catch {
      setListening(false);
    }
  };

  const newSession = async () => {
    if (thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再新建对话。');
      return;
    }
    try {
      const r = await api.createChatSession(userId);
      setSessions(r.sessions || []);
      const nextSessionId = r.current_session_id || r.session_id;
      setCurrentSessionId(nextSessionId);
      onSessionChange?.(nextSessionId);
      setMessages(normalizeChatMessages(r.messages));
      setInput('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '新建对话失败');
    }
  };

  const switchSession = async (sessionId: string) => {
    if (!sessionId || sessionId === currentSessionId || thinking || modelLoading) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再切换对话。');
      return;
    }
    try {
      const r = await api.switchChatSession(sessionId, userId);
      setSessions(r.sessions || []);
      const nextSessionId = r.current_session_id || sessionId;
      setCurrentSessionId(nextSessionId);
      onSessionChange?.(nextSessionId);
      setMessages(normalizeChatMessages(r.messages));
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换对话失败');
    }
  };

  const setInteractionMode = async (mode: 'chat_only' | 'tool_enabled') => {
    if (!currentSessionId || mode === currentInteractionMode || thinking) return;
    if (!userId) {
      setError('请先登录账号，再切换会话模式。');
      return;
    }
    setError('');
    try {
      const r = await api.setChatInteractionMode(currentSessionId, mode, userId);
      setSessions(r.sessions || []);
      if (r.current_session_id) setCurrentSessionId(r.current_session_id);
      if (r.messages) setMessages((current) => mergeServerMessages(current, normalizeChatMessages(r.messages)));
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换会话模式失败');
    }
  };

  const deleteSession = async () => {
    if (!currentSessionId || thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再管理对话。');
      return;
    }
    if (!window.confirm('删除当前对话？删除后该对话的聊天记录和会话级数据将不可恢复。')) return;
    try {
      const r = sessions.length > 1
        ? await api.deleteChatSession(currentSessionId, userId)
        : await api.clearChatSession(currentSessionId, userId);
      setSessions(r.sessions || []);
      const nextSessionId = r.current_session_id || '';
      setCurrentSessionId(nextSessionId);
      onSessionChange?.(nextSessionId);
      setMessages(normalizeChatMessages(r.messages));
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除对话失败');
    }
  };

  const beginEdit = (message: ChatMessage) => {
    if (!message.message_id || thinking) return;
    setEditingId(message.message_id);
    setEditText(message.content);
  };

  const retryEditedMessage = async () => {
    if (!editingId || thinking) return;
    const text = editText.trim();
    if (!text) return;
    if (!userId) {
      setError('请先登录账号，再重新生成回答。');
      return;
    }
    setThinking(true);
    setError('');
    try {
      const r = await api.retryMessage(editingId, text, userId, currentSessionId);
      setMessages((current) => mergeServerMessages(current, normalizeChatMessages(r.messages)));
      setSessions(r.sessions || []);
      const nextSessionId = r.current_session_id || currentSessionId;
      setCurrentSessionId(nextSessionId);
      onSessionChange?.(nextSessionId);
      setEditingId(null);
      setEditText('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新生成失败');
    } finally {
      setThinking(false);
    }
  };

  const uploadFiles = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    if (!userId) {
      setError('请先登录账号，再上传数据。');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }
    setUploading(true);
    setError('');
    try {
      const r = await api.uploadFiles(files, userId, currentSessionId);
      setWorkspaceMentions(normalizeWorkspaceMentions(r.dashboard?.datasets || []));
      const summary = r.outcome_markdown || '';
      setMessages((v) => [
        ...v,
        {
          role: 'system',
          content: summary || `已上传 ${r.count} 个文件。`,
          meta: { upload_summaries: r.upload_summaries || [] }
        }
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const runThesisWorkflow = async () => {
    if (thinking) return;
    if (!userId) {
      setError('请先登录账号，再运行论文流程。');
      return;
    }
    setThinking(true);
    setError('');
    const prompt = '一键检查并运行闪电河流域土壤水分融合论文流程。';
    setMessages((v) => [...v, { role: 'user', content: prompt }]);
    try {
      const r = await api.runSoilMoistureWorkflow(userId, currentSessionId);
      setMessages((v) => [...v, { role: 'assistant', content: assistantReplyContent(r.reply), meta: { model: r.model, reason: r.reason } }]);
      setLastFailedPrompt('');
    } catch (e) {
      const content = assistantErrorContent(e);
      setMessages((v) => [...v, { role: 'assistant', content, meta: { reason: 'error' } }]);
      setLastFailedPrompt(prompt);
      setError('');
    } finally {
      setThinking(false);
    }
  };

  const dragHandle = useMemo(() => ({
    onPointerDown: (e: PointerEvent) => {
      const startX = e.clientX;
      const startW = width;
      const move = (ev: globalThis.PointerEvent) => setWidth(Math.min(680, Math.max(360, startW + ev.clientX - startX)));
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    }
  }), [width]);

  const isPage = mode === 'page';
  const currentSession = visibleSessions.find((session) => session.session_id === currentSessionId);
  const workspaceBody = (
    <>
        <header data-testid="chat-conversation-header" className={cn('relative border-b border-slate-200/80 bg-white/82 shadow-[0_10px_30px_rgba(15,23,42,.04)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/78', isPage ? 'flex min-h-14 items-center gap-3 px-4 lg:col-start-2 lg:row-start-1' : 'flex flex-col gap-2 px-3 py-3')}>
          {!isPage ? (
            <>
              <div className="flex min-w-0 items-center gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2"><h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{currentSession?.title || '新对话'}</h1><RealtimeSyncIndicator state={realtimeSyncState} /></div>
                  <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messages.length} 条消息</p>
                </div>
                <button onClick={onClose} className="chat-icon-action" title="隐藏聊天" aria-label="隐藏聊天">
                  <ChevronsLeft size={18} strokeWidth={1.7} />
                </button>
              </div>
              <div data-testid="floating-chat-toolbar" className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] gap-2">
                {visibleSessions.length > 0 ? (
                  <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select min-w-0">
                    {visibleSessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
                  </select>
                ) : (
                  <button onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-compact-select min-w-0 text-left">新对话</button>
                )}
                <div className="relative min-w-0">
                  <select
                    data-testid="chat-model-selector"
                    value={chatModels?.selected_model || 'auto'}
                    onChange={(event) => changeChatModel(event.target.value)}
                    disabled={!userId || !currentSessionId || modelLoading || thinking}
                    className="chat-model-select w-full max-w-none"
                    title={chatModels?.selected_model === 'auto' ? '自动选择：根据任务内容选择模型' : chatModels?.selected_model || '自动选择'}
                  >
                    <option value="auto">自动选择</option>
                    {visibleModels.map((model) => (
                      <option key={model.id} value={model.id}>{model.id} · {model.capability === 'vision' ? '视觉' : '文本'}</option>
                    ))}
                  </select>
                  {(modelNotice || modelError) && <span className={cn('chat-model-notice', modelError && 'is-error')}>{modelError || modelNotice}</span>}
                </div>
                <button data-testid="chat-new-session-compact" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-icon-action" title="新建对话" aria-label="新建对话"><Plus size={17} /></button>
                <button data-testid="floating-chat-delete" onClick={deleteSession} disabled={thinking || modelLoading || !userId || !currentSessionId} className="chat-icon-action text-rose-500 hover:text-rose-600" title="删除当前对话" aria-label="删除当前对话"><Trash2 size={16} /></button>
              </div>
            </>
          ) : (
            <>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2"><h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{currentSession?.title || '新对话'}</h1><RealtimeSyncIndicator state={realtimeSyncState} /></div>
                <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messages.length} 条消息</p>
              </div>
              {visibleSessions.length > 0 && (
                <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select max-w-40 lg:hidden">
                  {visibleSessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
                </select>
              )}
              <button data-testid="chat-new-session-compact" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-icon-action lg:hidden" title="新建对话"><Plus size={17} /></button>
              <div className="relative min-w-0">
                <select
                  data-testid="chat-model-selector"
                  value={chatModels?.selected_model || 'auto'}
                  onChange={(event) => changeChatModel(event.target.value)}
                  disabled={!userId || !currentSessionId || modelLoading || thinking}
                  className="chat-model-select"
                  title={chatModels?.selected_model === 'auto' ? '自动选择：根据任务内容选择模型' : chatModels?.selected_model || '自动选择'}
                >
                  <option value="auto">自动选择</option>
                  {visibleModels.map((model) => (
                    <option key={model.id} value={model.id}>{model.id} · {model.capability === 'vision' ? '视觉' : '文本'}</option>
                  ))}
                </select>
                {(modelNotice || modelError) && <span className={cn('chat-model-notice', modelError && 'is-error')}>{modelError || modelNotice}</span>}
              </div>
              <button data-testid="chat-upload-button" onClick={() => fileInputRef.current?.click()} disabled={uploading || !userId} className="chat-secondary-action hidden sm:inline-flex">
                <UploadCloud size={15} strokeWidth={1.8} /> {uploading ? '上传中...' : '上传数据'}
              </button>
              <button onClick={runThesisWorkflow} disabled={thinking || !userId} className="chat-icon-action" title="运行论文流程">
                <PlayCircle size={17} strokeWidth={1.7} />
              </button>
            </>
          )}
          <input
            ref={fileInputRef}
            data-testid="chat-file-input"
            type="file"
            multiple
            className="hidden"
            accept=".zip,.shp,.shx,.dbf,.prj,.cpg,.geojson,.gpkg,.kml,.csv,.xlsx,.xls,.tif,.tiff,.img,.docx,.txt,.md"
            onChange={(event) => uploadFiles(event.target.files)}
          />
        </header>

        {isPage && (
          <aside data-testid="chat-session-list" className="chat-session-rail lg:col-start-1 lg:row-span-3 lg:row-start-1">
            <button data-testid="chat-new-session" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-primary-action w-full">
              <Plus size={16} strokeWidth={2} /> 新建对话
            </button>
            <div className="mt-5 flex items-center justify-between px-2 text-[11px] font-bold uppercase tracking-[0.08em] text-slate-400">
              <span>最近对话</span><span>{visibleSessions.length}</span>
            </div>
            <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
              {visibleSessions.map((session) => {
                const active = session.session_id === currentSessionId;
                return (
                  <button key={session.session_id} onClick={() => switchSession(session.session_id)} disabled={thinking || modelLoading} className={cn('chat-session-row group', active && 'is-active')}>
                    <MessageSquare size={15} strokeWidth={1.7} className="mt-0.5 shrink-0" />
                    <span className="min-w-0 flex-1 text-left">
                      <span className="block truncate font-semibold">{session.title || '新对话'}</span>
                      <span className="mt-1 block text-[10px] font-medium opacity-60">{sessionDate(session) || (active ? `${messages.length} 条消息` : '历史对话')}</span>
                    </span>
                  </button>
                );
              })}
              {!userId && <div className="px-3 py-8 text-center text-xs leading-5 text-slate-400">登录后显示对话记录</div>}
            </div>
            <button onClick={deleteSession} disabled={thinking || modelLoading || !userId || !currentSessionId} className="chat-danger-action mt-3 w-full">
              <Trash2 size={15} /> 删除当前对话
            </button>
          </aside>
        )}

        <div
          ref={listRef}
          onScroll={(event) => {
            const target = event.currentTarget;
            stickToBottomRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 96;
          }}
          className={cn('chat-scroll relative flex-1 space-y-4 overflow-y-auto bg-gradient-to-b from-slate-50/35 to-white/35 px-4 pb-24 pt-5 lg:pb-5 dark:from-slate-950/20 dark:to-slate-900/20', isPage && 'min-h-0 px-6 lg:col-start-2 lg:row-start-2')}
        >
          {messages.length === 0 && (
            <div data-testid="chat-empty-state" className="mx-auto flex min-h-full max-w-3xl flex-col justify-center py-8">
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 text-blue-600 shadow-inner dark:from-blue-950/50 dark:to-cyan-950/30 dark:text-cyan-300"><Sparkles size={20} strokeWidth={1.8} /></div>
                <div><h2 className="text-xl font-bold tracking-tight text-slate-950 dark:text-slate-50">今天想处理什么？</h2><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">直接描述目标，我会结合当前工作区完成 GIS 任务。</p></div>
              </div>
              <div className="mt-7 grid gap-3 sm:grid-cols-2">
                {PROMPT_GROUPS.map((group) => {
                  const Icon = group.icon;
                  return (
                    <button key={group.title} onClick={() => sendPrompt(group.prompt)} className="chat-prompt-card">
                      <Icon size={18} strokeWidth={1.7} />
                      <span><strong>{group.title}</strong><small>{group.description}</small></span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <AnimatePresence initial={false}>
            {renderMessages.map((m) => {
              const isUser = m.role === 'user';
              const isSystem = m.role === 'system';
              const isEditing = isUser && m.message_id && editingId === m.message_id;
              const isToolTask = !isUser && !isSystem && messageIsToolTask(m);
              return (
                <motion.div key={messageKey(m)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
                  <div className={cn(
                    'group min-w-0 whitespace-pre-wrap break-words text-sm leading-6',
                    !isToolTask && 'rounded-[22px] px-4 py-3 shadow-[0_14px_32px_rgba(15,23,42,.09)]',
                    isUser && 'max-w-[min(66%,34rem)] rounded-[18px] bg-gradient-to-br from-blue-600 to-cyan-600 px-3.5 py-2.5 text-white shadow-[0_12px_26px_rgba(15,98,254,.18)]',
                    !isUser && (isToolTask ? 'w-full max-w-[min(96%,58rem)]' : 'max-w-[min(86%,48rem)]'),
                    !isUser && !isSystem && 'border border-slate-200/80 bg-white/78 text-slate-700 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/55 dark:text-slate-200',
                    isToolTask && 'border-0 bg-transparent p-0 shadow-none backdrop-blur-0 dark:bg-transparent',
                    isSystem && 'border border-emerald-300/35 bg-emerald-50/80 text-emerald-700 backdrop-blur-xl dark:bg-emerald-950/30 dark:text-emerald-200'
                  )}>
                    {isSystem && <FileUp className="mr-2 inline" size={15} strokeWidth={1.7} />}
                    {isEditing ? (
                      <div className="space-y-2">
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          className="min-h-24 w-full resize-y rounded-2xl border border-white/40 bg-white/95 px-3 py-2 text-slate-900 outline-none"
                        />
                        <div className="flex justify-end gap-2">
                          <button onClick={() => setEditingId(null)} className="rounded-xl bg-white/20 p-2" title="取消"><X size={15} /></button>
                          <button onClick={retryEditedMessage} className="rounded-xl bg-white/25 p-2" title="保存并重新生成"><Check size={15} /></button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {!isUser && !isSystem && <MessageSourceBadge message={m} />}
                        {isSystem && Array.isArray(m.meta?.upload_summaries) && <UploadResultCard summaries={m.meta.upload_summaries} />}
                        <ChatMessageRenderer
                          message={m}
                          content={isUser || isSystem ? m.content : assistantReplyContent(m.content)}
                          isUser={isUser}
                          isSystem={isSystem}
                          resumeReady={resumeReadyJobIds.has(String(m.meta?.action_required?.job_id || ''))}
                          onLogin={openGSCloudLogin}
                          onResume={resumeDownload}
                          onCancel={cancelDownload}
                          onRetry={retryDownload}
                          onClarification={chooseClarification}
                          onConfirmAction={confirmAction}
                          sessionId={currentSessionId}
                        />
                        {!isUser && !isSystem && m.meta?.reason === 'error' && lastFailedPrompt && (
                          <button onClick={() => sendPrompt(lastFailedPrompt)} disabled={thinking} className="mt-3 inline-flex items-center gap-1 rounded-full bg-white/55 px-3 py-1 text-xs font-black text-coral transition-colors hover:bg-white/80 disabled:opacity-50 dark:bg-white/10">
                            <RefreshCcw size={13} /> 重试
                          </button>
                        )}
                        {isUser && m.message_id && (
                          <button onClick={() => beginEdit(m)} className="pointer-events-none ml-2 inline-flex translate-y-0.5 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100" title="编辑并重新生成">
                            <Pencil size={14} strokeWidth={1.7} />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
          {thinking && <div className="flex justify-start"><ThinkingStatusCard mode={currentInteractionMode} /></div>}
          {error && <div className="rounded-2xl border border-coral/30 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</div>}
        </div>

        <div
          className={cn('shrink-0 border-t border-slate-200/80 bg-white/86 px-4 pt-4 shadow-[0_-12px_34px_rgba(15,23,42,.04)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/82', isPage && 'lg:col-start-2 lg:row-start-3')}
          style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
        >
          <div className="mb-2 flex flex-wrap gap-2">
            {QUICK_PROMPTS.slice(0, 2).map((p) => (
              <button key={p} onClick={() => sendPrompt(p)} className="chat-quick-prompt">
                {p.slice(0, 18)}...
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2" aria-label="会话交互模式">
              <div className="inline-flex rounded-2xl border border-slate-200 bg-white/80 p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900/75">
                <button
                  type="button"
                  data-testid="interaction-mode-chat"
                  className={cn('inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-black transition-colors', currentInteractionMode === 'chat_only' ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/10')}
                  title="聊天模式：只回答问题，不操作数据"
                  aria-pressed={currentInteractionMode === 'chat_only'}
                  disabled={thinking || !userId}
                  onClick={() => setInteractionMode('chat_only')}
                >
                  <MessageSquare size={14} /> 聊天
                </button>
                <button
                  type="button"
                  data-testid="interaction-mode-tool"
                  className={cn('inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-black transition-colors', currentInteractionMode === 'tool_enabled' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/10')}
                  title="工具模式：经计划和校验后执行工具"
                  aria-pressed={currentInteractionMode === 'tool_enabled'}
                  disabled={thinking || !userId}
                  onClick={() => setInteractionMode('tool_enabled')}
                >
                  <Wrench size={14} /> 工具
                </button>
              </div>
              <div className="max-w-full text-[11px] leading-snug text-slate-500 dark:text-slate-400">{interactionModeLabel}</div>
            </div>
            <div className="min-w-0 flex-1">
              <ChatComposer
                value={input}
                onChange={setInput}
                onSend={send}
                onUpload={uploadFiles}
                onStop={stopCurrentRequest}
                sending={thinking}
                uploading={uploading}
                disabled={!userId}
                voiceSupported={voiceSupported}
                listening={listening}
                voiceUnavailableReason={voiceUnavailableReason}
                onVoiceToggle={toggleVoice}
                mentionItems={workspaceMentions}
              />
            </div>
          </div>
        </div>
        {!isPage && <div {...dragHandle} className="absolute right-0 top-0 h-full w-2 cursor-ew-resize" />}
        <ModalPortal>
          <AnimatePresence>
            {gscloudLoginOpen && (
              <motion.div className="fixed inset-0 z-[95] grid place-items-end bg-slate-950/30 p-3 backdrop-blur-sm sm:place-items-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <motion.div data-testid="gscloud-login-dialog" className="max-h-[calc(100dvh-1.5rem)] w-full max-w-md overflow-y-auto rounded-[24px] border border-white/35 bg-white p-4 shadow-2xl dark:border-white/10 dark:bg-slate-900" initial={{ y: 18, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 18, opacity: 0 }}>
                  <div className="mb-3 flex items-center justify-between">
                    <div><div className="font-black">登录数据源账号</div><p className="text-xs text-slate-500">登录成功后可继续当前下载任务</p></div>
                    <button type="button" onClick={() => setGSCloudLoginOpen(false)} className="chat-icon-action" aria-label="关闭登录引导"><X size={17} /></button>
                  </div>
                  <GSCloudAccountPanel enabled={Boolean(userId)} pendingJobId={pendingLoginJobId} onLoginComplete={markGSCloudLoginComplete} />
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>
        </ModalPortal>
    </>
  );

  if (isPage) {
    return (
      <section
        data-testid="chat-page-workspace"
        className="relative flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-200/90 bg-white/82 shadow-[0_22px_60px_rgba(51,65,85,.10)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/78 lg:grid lg:h-[calc(100vh-11rem)] lg:min-h-[620px] lg:grid-cols-[240px_minmax(0,1fr)] lg:grid-rows-[auto_minmax(0,1fr)_auto]"
      >
        {workspaceBody}
      </section>
    );
  }

  return (
    <motion.aside
      ref={panelRef}
      style={{ width: `min(${width}px, calc(100vw - 1.5rem))`, minWidth: 'min(360px, calc(100vw - 1.5rem))' }}
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      exit={{ opacity: 0, x: -24, scale: 0.98 }}
      className="no-drag fixed bottom-4 left-3 top-8 z-30 flex max-w-[680px] flex-col rounded-[28px] sm:left-4"
    >
      <GlassCard className="relative flex h-full flex-col overflow-hidden p-0">
        {workspaceBody}
      </GlassCard>
    </motion.aside>
  );
}

export function ChatPanel(props: Omit<ChatWorkspaceProps, 'mode'>) {
  return <ChatWorkspace {...props} mode="floating" />;
}
