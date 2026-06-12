import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Bot, Check, ChevronsLeft, Database, FileUp, MessageSquare, Mic, Pencil, PlayCircle, Plus, RefreshCcw, SendHorizontal, Sparkles, Trash2, UploadCloud, Waves, X } from 'lucide-react';
import { api, ChatMessage, ChatSession, CommercialUser, ResultPanel, WorkspaceDashboard } from '@/lib/api';
import { GlassCard } from './GlassCard';
import { AuthPanel } from './AuthPanel';
import { cn } from '@/lib/cn';
import { isLocalSecureContext } from './mapLayerPolicy';
import { parseMapTextCommand, type ParsedMapTextCommand } from './mapTextCommands';
import { assistantErrorContent, assistantReplyContent, normalizeChatMessages } from './chatMessageContent';
import type { ChatContextPayload } from '@/lib/chatContext';

export type ExternalPromptCommand = { id: number; prompt: string };

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
    title: '数据检查',
    prompts: [
      '概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。',
      '检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。'
    ]
  },
  {
    title: '制图建模',
    prompts: [
      '按照闪电河流域土壤水分融合论文流程，检查能否做 BTCH、RF、XGBoost、LSTM 与 GCP。'
    ]
  },
  {
    title: '下载准备',
    prompts: [
      '根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。'
    ]
  }
];

const PROMPT_GROUPS_FIXED = [
  {
    title: '数据检查',
    prompts: [
      '概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。',
      '检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。'
    ]
  },
  {
    title: '制图建模',
    prompts: [
      '按照闪电河流域土壤水分融合论文流程，检查能否做 BTCH、RF、XGBoost、LSTM 与 GCP。'
    ]
  },
  {
    title: '下载准备',
    prompts: [
      '根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。'
    ]
  }
];

const QUICK_PROMPTS = PROMPT_GROUPS_FIXED.flatMap((group) => group.prompts);

function numberValue(value: unknown) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}

function WorkspaceQuickStats({ dashboard }: { dashboard: WorkspaceDashboard | null }) {
  const counts = dashboard?.dataset_type_counts || {};
  const total = numberValue(counts.table) + numberValue(counts.vector) + numberValue(counts.raster) + numberValue(counts.document);
  const runtime = dashboard?.runtime_status || {};
  const status = String(runtime.label || '就绪');
  return (
    <div className="rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-black text-slate-600 dark:text-slate-300"><Database size={14} strokeWidth={1.7} /> 数据概览</div>
        <span className="rounded-full bg-white/45 px-2 py-0.5 text-[11px] font-black text-slate-500 dark:bg-white/10 dark:text-slate-300">{status}</span>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        {[
          ['总数', total],
          ['表格', counts.table || 0],
          ['矢量', counts.vector || 0],
          ['栅格', counts.raster || 0]
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-2xl bg-white/40 px-2 py-2 dark:bg-white/5">
            <div className="text-sm font-black text-ocean dark:text-cyan-glow">{String(value)}</div>
            <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">{String(label)}</div>
          </div>
        ))}
      </div>
    </div>
  );
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

export function ChatPanel({
  user,
  setUser,
  onClose,
  onMapTextCommand,
  externalPrompt,
  onResultPanel,
  chatContext = {}
}: {
  user: CommercialUser | null;
  setUser: (u: CommercialUser | null) => void;
  onClose?: () => void;
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  externalPrompt?: ExternalPromptCommand | null;
  onResultPanel?: (panel: ResultPanel) => void;
  chatContext?: ChatContextPayload;
}) {
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
  const [dashboard, setDashboard] = useState<WorkspaceDashboard | null>(null);
  const [lastFailedPrompt, setLastFailedPrompt] = useState('');
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceUnavailableReason, setVoiceUnavailableReason] = useState('');
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<unknown>(null);
  const userId = user?.user_id || '';

  const refreshDashboard = async () => {
    try {
      setDashboard(await api.dashboard(userId));
    } catch {
      setDashboard(null);
    }
  };

  const refreshSessions = async () => {
    if (!userId) {
      setSessions([]);
      setCurrentSessionId('');
      setMessages([]);
      return;
    }
    const r = await api.chatSessions(userId);
    setSessions(r.sessions || []);
    setCurrentSessionId(r.current_session_id || '');
    setMessages(normalizeChatMessages(r.messages));
    refreshDashboard().catch(() => {});
  };

  useEffect(() => {
    refreshSessions().catch(() => {
      setSessions([]);
      setCurrentSessionId('');
      setMessages([]);
    });
    refreshDashboard().catch(() => {});
  }, [userId]);

  useEffect(() => {
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
    setMessages((v) => [...v, { role: 'user', content: text }]);
    setThinking(true);
    try {
      const r = await api.ask(text, userId, currentSessionId, { ...chatContext, session_id: currentSessionId });
      if (r.messages) setMessages(normalizeChatMessages(r.messages));
      else setMessages((v) => [...v, { role: 'assistant', content: assistantReplyContent(r.reply), meta: { model: r.model, reason: r.reason } }]);
      if (r.sessions) setSessions(r.sessions);
      if (r.result_panel) onResultPanel?.(r.result_panel);
      setCurrentSessionId(r.current_session_id || currentSessionId);
      setLastFailedPrompt('');
      refreshSessions().catch(() => {});
    } catch (e) {
      const content = assistantErrorContent(e);
      setMessages((v) => [...v, { role: 'assistant', content, meta: { reason: 'error' } }]);
      setLastFailedPrompt(text);
      setError('');
    } finally {
      setThinking(false);
    }
  };

  const send = () => sendPrompt(input);

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
      setCurrentSessionId(r.current_session_id || r.session_id);
      setMessages(normalizeChatMessages(r.messages));
      setInput('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '新建对话失败');
    }
  };

  const switchSession = async (sessionId: string) => {
    if (!sessionId || sessionId === currentSessionId || thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再切换对话。');
      return;
    }
    try {
      const r = await api.switchChatSession(sessionId, userId);
      setSessions(r.sessions || []);
      setCurrentSessionId(r.current_session_id || sessionId);
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
      setCurrentSessionId(r.current_session_id || '');
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
      setCurrentSessionId(r.current_session_id || currentSessionId);
      setEditingId(null);
      setEditText('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新生成失败');
    } finally {
      setThinking(false);
    }
  };

  const uploadFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!userId) {
      setError('请先登录账号，再上传数据。');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }
    setUploading(true);
    setError('');
    try {
      const r = await api.uploadFiles(files, userId);
      const summary = [r.messages.join('\n\n'), r.outcome_markdown || ''].filter(Boolean).join('\n\n');
      setDashboard(r.dashboard);
      appendSystem(`已上传并载入 ${r.count} 个文件。\n${summary}`);
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
      const r = await api.runSoilMoistureWorkflow(userId);
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
        <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/55 to-transparent dark:from-white/5" />
        <header className="relative flex items-center gap-3 border-b border-white/30 px-4 py-3 dark:border-white/10">
          <div className="relative grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow">
            <motion.span className="absolute inset-0 rounded-2xl border border-cyan-glow/50" animate={{ scale: [1, 1.22, 1], opacity: [0.9, 0, 0.9] }} transition={{ duration: 2.2, repeat: Infinity }} />
            <Bot size={22} strokeWidth={1.5} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-lg font-black tracking-tight text-slate-950 dark:text-slate-50">智能助手</h1>
              <span className="rounded-full border border-cyan-glow/25 bg-cyan-glow/10 px-2 py-0.5 text-[11px] font-black text-ocean dark:text-cyan-glow">GIS Agent</span>
            </div>
            <p className="truncate text-sm text-slate-500 dark:text-slate-400">上传数据 · 自主处理 · 制图建模 · 结果追问</p>
          </div>
          <div className="hidden rounded-full border border-cyan-glow/20 bg-cyan-glow/10 p-2 text-cyan-glow sm:block">
            <Waves size={18} strokeWidth={1.5} />
          </div>
          <button onClick={onClose} className="glass-button h-10 w-10 shrink-0 rounded-2xl p-0" title="隐藏智能助手">
            <ChevronsLeft size={18} strokeWidth={1.7} />
          </button>
        </header>

        <div className="space-y-3 px-4 pt-3">
          <AuthPanel user={user} setUser={setUser} />
          <WorkspaceQuickStats dashboard={dashboard} />
          <div className="rounded-[18px] border border-white/30 bg-white/35 p-2.5 dark:border-white/10 dark:bg-slate-950/20">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-black text-slate-500 dark:text-slate-400">
                <MessageSquare size={14} strokeWidth={1.7} /> 对话
              </div>
              <div className="text-[11px] font-semibold text-slate-400">{messages.length} 条消息</div>
            </div>
            <div className="flex gap-2">
              <select
                value={currentSessionId}
                onChange={(e) => switchSession(e.target.value)}
                disabled={!userId || thinking}
                className="min-w-0 flex-1 rounded-2xl border border-white/30 bg-white/50 px-3 py-2 text-xs font-semibold outline-none dark:border-white/10 dark:bg-slate-900/50"
              >
                {!userId && <option value="">登录后显示对话记录</option>}
                {sessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>{s.title || '新对话'}</option>
                ))}
              </select>
              <button onClick={newSession} disabled={thinking || !userId} className="glass-button h-9 w-9 rounded-2xl p-0 disabled:opacity-60" title="新建对话"><Plus size={16} /></button>
              <button onClick={deleteSession} disabled={thinking || !userId || !currentSessionId} className="glass-button h-9 w-9 rounded-2xl p-0 text-coral disabled:opacity-40" title="删除当前对话"><Trash2 size={15} /></button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button data-testid="chat-upload-button" onClick={() => fileInputRef.current?.click()} disabled={uploading || !userId} className="glass-button gap-2 rounded-2xl text-xs font-black disabled:opacity-60">
              <UploadCloud size={15} strokeWidth={1.7} /> {uploading ? '上传中...' : '上传数据'}
            </button>
            <button onClick={runThesisWorkflow} disabled={thinking || !userId} className="glass-button gap-2 rounded-2xl text-xs font-black disabled:opacity-60">
              <PlayCircle size={15} strokeWidth={1.7} /> 论文流程
            </button>
            <input
              ref={fileInputRef}
              data-testid="chat-file-input"
              type="file"
              multiple
              className="hidden"
              accept=".zip,.shp,.shx,.dbf,.prj,.cpg,.geojson,.gpkg,.kml,.csv,.xlsx,.xls,.tif,.tiff,.img,.docx,.txt,.md"
              onChange={(e) => uploadFiles(e.target.files)}
            />
          </div>
        </div>

        <div ref={listRef} className="chat-scroll relative flex-1 space-y-4 overflow-y-auto px-4 py-5">
          {messages.length === 0 && (
            <div className="rounded-[24px] border border-white/40 bg-white/35 p-5 text-sm text-slate-600 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/30 dark:text-slate-300">
              <div className="mb-3 flex items-center gap-2 font-black text-slate-950 dark:text-slate-50"><Sparkles size={16} /> 试试这样问</div>
              <div className="space-y-3">
                {PROMPT_GROUPS_FIXED.map((group) => (
                  <div key={group.title}>
                    <div className="mb-1 text-[11px] font-black text-slate-400">{group.title}</div>
                    <div className="space-y-2">
                      {group.prompts.map((p) => (
                        <button key={p} onClick={() => sendPrompt(p)} className="block w-full rounded-2xl border border-white/30 bg-white/35 px-3 py-2 text-left text-xs leading-5 transition hover:bg-white/60 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10">
                          {p}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <AnimatePresence initial={false}>
            {messages.map((m, idx) => {
              const isUser = m.role === 'user';
              const isSystem = m.role === 'system';
              const isEditing = isUser && m.message_id && editingId === m.message_id;
              return (
                <motion.div key={`${m.role}-${idx}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
                  <div className={cn(
                    'group max-w-[92%] overflow-hidden whitespace-pre-wrap break-words rounded-[22px] px-4 py-3 text-sm leading-6 shadow-lg',
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
                        <MarkdownMessage content={isUser || isSystem ? m.content : assistantReplyContent(m.content)} />
                        {!isUser && !isSystem && m.meta?.reason === 'error' && lastFailedPrompt && (
                          <button onClick={() => sendPrompt(lastFailedPrompt)} disabled={thinking} className="mt-3 inline-flex items-center gap-1 rounded-full bg-white/55 px-3 py-1 text-xs font-black text-coral transition hover:bg-white/80 disabled:opacity-50 dark:bg-white/10">
                            <RefreshCcw size={13} /> 重试
                          </button>
                        )}
                        {isUser && m.message_id && (
                          <button onClick={() => beginEdit(m)} className="ml-2 inline-flex translate-y-0.5 opacity-0 transition group-hover:opacity-100" title="编辑并重新生成">
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

        <div className="border-t border-white/30 p-4 dark:border-white/10">
          <div className="mb-2 flex flex-wrap gap-2">
            {QUICK_PROMPTS.slice(0, 2).map((p) => (
              <button key={p} onClick={() => sendPrompt(p)} className="rounded-full border border-white/35 bg-white/45 px-3 py-1.5 text-[11px] font-semibold text-slate-500 transition hover:bg-white/70 dark:border-white/10 dark:bg-white/5 dark:text-slate-300">
                {p.slice(0, 18)}...
              </button>
            ))}
          </div>
          <div className="flex items-end gap-2 rounded-[20px] border border-white/50 bg-white/55 p-2 shadow-[0_18px_50px_rgba(15,23,42,.08)] backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/35">
            <button
              onClick={toggleVoice}
              className={cn('glass-button h-10 w-10 shrink-0 rounded-2xl p-0 text-slate-500', listening && 'bg-gradient-to-r from-ocean to-cyan-glow text-white shadow-glow')}
              title={listening ? '停止语音输入' : '语音输入'}
            >
              <Mic size={18} strokeWidth={1.5} />
            </button>
            <textarea
              data-testid="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="输入数据下载、融合建模、精度验证、制图或结果追问..."
              className="max-h-28 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-400"
            />
            <button data-testid="chat-send" onClick={send} disabled={thinking || !input.trim()} className="primary-button h-10 w-10 shrink-0 rounded-2xl p-0 disabled:opacity-45"><SendHorizontal size={18} strokeWidth={1.5} /></button>
          </div>
        </div>
        <div {...dragHandle} className="absolute right-0 top-0 h-full w-2 cursor-ew-resize" />
      </GlassCard>
    </motion.aside>
  );
}
