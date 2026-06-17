import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Check, ChevronsLeft, FileUp, Map as MapIcon, MessageSquare, Pencil, PlayCircle, Plus, RefreshCcw, SearchCheck, Sparkles, Trash2, UploadCloud, X } from 'lucide-react';
import { api, ChatMessage, ChatModelState, ChatSession, CommercialUser, ResultPanel, WorkspaceMention } from '@/lib/api';
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
  return String(text || '').split(/(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*)/g).map((part, idx) => {
    const bold = part.match(/^\*{2,3}(.+)\*{2,3}$/);
    return bold ? <strong key={idx} className="font-black text-inherit">{bold[1]}</strong> : <span key={idx}>{part}</span>;
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

function MarkdownMessage({ content }: { content: string }) {
  const lines = String(content || '').split(/\r?\n/);
  return (
    <div className="chat-markdown">
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={idx} className="h-2" />;
        const heading = trimmed.match(/^#{1,6}\s+(.+)$/);
        if (heading) return <div key={idx} className="chat-md-heading">{renderInlineMarkdown(heading[1])}</div>;
        if (/^\*{3,}$/.test(trimmed) || /^-{3,}$/.test(trimmed)) return <div key={idx} className="chat-md-rule" />;
        const bullet = trimmed.match(/^[-*]\s+(.+)$/);
        if (bullet) return <div key={idx} className="chat-md-list"><span>•</span><span>{renderInlineMarkdown(bullet[1])}</span></div>;
        const numbered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
        if (numbered) return <div key={idx} className="chat-md-list"><span>{numbered[1]}.</span><span>{renderInlineMarkdown(numbered[2])}</span></div>;
        return <div key={idx}>{renderInlineMarkdown(line)}</div>;
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
  const [modelNotice, setModelNotice] = useState('');
  const [modelError, setModelError] = useState('');
  const [workspaceMentions, setWorkspaceMentions] = useState<WorkspaceMention[]>(() => normalizeWorkspaceMentions(mentionDatasets));
  const [gscloudLoginOpen, setGSCloudLoginOpen] = useState(false);
  const [pendingLoginJobId, setPendingLoginJobId] = useState('');
  const [resumeReadyJobIds, setResumeReadyJobIds] = useState<Set<string>>(() => new Set());
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<unknown>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeTaskIdRef = useRef<string>('');
  const stickToBottomRef = useRef(true);
  const handledLoginMessageRef = useRef('');
  const announcedDownloadJobsRef = useRef<Set<string>>(new Set());
  const mountedRef = useRef(true);
  const userId = user?.user_id || '';

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refreshSessions = async () => {
    if (!userId) {
      setSessions([]);
      setCurrentSessionId('');
      onSessionChange?.('');
      setMessages([]);
      return;
    }
    const r = await api.chatSessions(userId);
    setSessions(r.sessions || []);
    setCurrentSessionId(r.current_session_id || '');
    onSessionChange?.(r.current_session_id || '');
    setMessages((current) => {
      if ((!r.messages || r.messages.length === 0) && current.length > 0) return current;
      return mergeStableClientMessageIds(current, normalizeChatMessages(r.messages));
    });
  };

  useEffect(() => {
    refreshSessions().catch(() => {
      setSessions([]);
      setCurrentSessionId('');
      setMessages([]);
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
        const job = result.jobs.find((item) => item.job_id === jobId);
        if (!job) continue;
        if ((job.status === 'completed' || job.status === 'success') && !announcedDownloadJobsRef.current.has(jobId)) {
          announcedDownloadJobsRef.current.add(jobId);
          setMessages((current) => [...current, {
            role: 'assistant',
            content: '下载完成。结果文件已注册，可以直接下载。',
            meta: { artifacts: job.artifacts || [], reason: 'download_success' }
          }]);
          return;
        }
        if (job.status === 'failed' || job.status === 'canceled' || job.status === 'cancelled') {
          setMessages((current) => [...current, { role: 'assistant', content: job.error_message || '下载任务未完成。', meta: { reason: 'download_failed' } }]);
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
      setMessages((current) => [...current, { role: 'assistant', content, meta: { reason: result.reason || 'download_resume' } }]);
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
      setMessages((current) => [...current, { role: 'assistant', content: '下载任务已取消。', meta: { reason: 'download_cancelled' } }]);
      setGSCloudLoginOpen(false);
    } catch (cause) {
      setMessages((current) => [...current, { role: 'assistant', content: assistantErrorContent(cause), meta: { reason: 'error' } }]);
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
    setMessages((v) => [...v, optimisticUserMessage]);
    setThinking(true);
    const controller = new AbortController();
    const taskId = `chat_${Date.now()}_${hashString(text)}`;
    abortRef.current = controller;
    activeTaskIdRef.current = taskId;
    try {
      const r = await api.ask(text, userId, currentSessionId, { ...chatContext, session_id: currentSessionId }, controller.signal, taskId);
      if (r.messages) setMessages((current) => mergeStableClientMessageIds(current, normalizeChatMessages(r.messages)));
      else setMessages((v) => [...v, { role: 'assistant', content: assistantReplyContent(r.reply), meta: { model: r.model, reason: r.reason } }]);
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
      setLastFailedPrompt(text);
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

  const deleteSession = async () => {
    if (!currentSessionId || thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再管理对话。');
      return;
    }
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
      setMessages(normalizeChatMessages(r.messages));
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
  const currentSession = sessions.find((session) => session.session_id === currentSessionId);
  const workspaceBody = (
    <>
        <header data-testid="chat-conversation-header" className={cn('relative border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900', isPage ? 'flex min-h-14 items-center gap-3 px-4 lg:col-start-2 lg:row-start-1' : 'flex flex-col gap-2 px-3 py-3')}>
          {!isPage ? (
            <>
              <div className="flex min-w-0 items-center gap-2">
                <div className="min-w-0 flex-1">
                  <h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{currentSession?.title || '新对话'}</h1>
                  <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messages.length} 条消息</p>
                </div>
                <button onClick={onClose} className="chat-icon-action" title="隐藏聊天" aria-label="隐藏聊天">
                  <ChevronsLeft size={18} strokeWidth={1.7} />
                </button>
              </div>
              <div data-testid="floating-chat-toolbar" className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] gap-2">
                {sessions.length > 0 ? (
                  <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select min-w-0">
                    {sessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
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
                    {(chatModels?.models || []).map((model) => (
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
                <h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{currentSession?.title || '新对话'}</h1>
                <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messages.length} 条消息</p>
              </div>
              {sessions.length > 0 && (
                <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select max-w-40 lg:hidden">
                  {sessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
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
                  {(chatModels?.models || []).map((model) => (
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
              <span>最近对话</span><span>{sessions.length}</span>
            </div>
            <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
              {sessions.map((session) => {
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
          className={cn('chat-scroll relative flex-1 space-y-4 overflow-y-auto px-4 pb-24 pt-5 lg:pb-5', isPage && 'min-h-0 bg-white px-6 dark:bg-slate-900 lg:col-start-2 lg:row-start-2')}
        >
          {messages.length === 0 && (
            <div data-testid="chat-empty-state" className="mx-auto flex min-h-full max-w-3xl flex-col justify-center py-8">
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300"><Sparkles size={20} strokeWidth={1.8} /></div>
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
            {messages.map((m, idx) => {
              const isUser = m.role === 'user';
              const isSystem = m.role === 'system';
              const isEditing = isUser && m.message_id && editingId === m.message_id;
              return (
                <motion.div key={messageKey(m)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
                  <div className={cn(
                    'group min-w-0 max-w-[92%] whitespace-pre-wrap break-words rounded-[22px] px-4 py-3 text-sm leading-6 shadow-lg',
                    isUser && 'bg-gradient-to-br from-ocean to-cyan-glow text-white',
                    !isUser && !isSystem && 'border border-white/40 bg-white/55 text-slate-700 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/45 dark:text-slate-200',
                    isSystem && 'border border-emerald-300/30 bg-emerald-400/10 text-emerald-700 backdrop-blur-xl dark:text-emerald-200'
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
                          onClarification={chooseClarification}
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
          {thinking && <div className="flex justify-start"><div className="rounded-2xl border border-white/40 bg-white/50 px-4 py-3 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/45"><ThinkingDots /></div></div>}
          {error && <div className="rounded-2xl border border-coral/30 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</div>}
        </div>

        <div
          className={cn('shrink-0 border-t border-slate-200 bg-white px-4 pt-4 dark:border-slate-800 dark:bg-slate-900', isPage && 'lg:col-start-2 lg:row-start-3')}
          style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
        >
          <div className="mb-2 flex flex-wrap gap-2">
            {QUICK_PROMPTS.slice(0, 2).map((p) => (
              <button key={p} onClick={() => sendPrompt(p)} className="chat-quick-prompt">
                {p.slice(0, 18)}...
              </button>
            ))}
          </div>
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
        className="relative flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_50px_rgba(51,65,85,.10)] dark:border-slate-800 dark:bg-slate-900 lg:grid lg:h-[calc(100vh-11rem)] lg:min-h-[620px] lg:grid-cols-[240px_minmax(0,1fr)] lg:grid-rows-[auto_minmax(0,1fr)_auto]"
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
