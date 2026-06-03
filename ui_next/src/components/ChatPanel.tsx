import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Bot, Check, ChevronsLeft, FileUp, MessageSquare, Mic, Pencil, PlayCircle, Plus, SendHorizontal, Sparkles, Trash2, UploadCloud, Waves, X } from 'lucide-react';
import { api, ChatMessage, ChatSession, CommercialUser } from '@/lib/api';
import { GlassCard } from './GlassCard';
import { AuthPanel } from './AuthPanel';
import { cn } from '@/lib/cn';
import { isLocalSecureContext } from './mapLayerPolicy';
import { parseMapTextCommand, type ParsedMapTextCommand } from './mapTextCommands';

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

const QUICK_PROMPTS = [
  '概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。',
  '检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。',
  '按照闪电河流域土壤水分融合论文流程，检查能否做 BTCH、RF、XGBoost、LSTM 与 GCP。'
];

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
  externalPrompt
}: {
  user: CommercialUser | null;
  setUser: (u: CommercialUser | null) => void;
  onClose?: () => void;
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  externalPrompt?: ExternalPromptCommand | null;
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
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceUnavailableReason, setVoiceUnavailableReason] = useState('');
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<unknown>(null);
  const userId = user?.user_id || '';

  const refreshSessions = async () => {
    const r = await api.chatSessions(userId);
    setSessions(r.sessions || []);
    setCurrentSessionId(r.current_session_id || '');
    setMessages(r.messages || []);
  };

  useEffect(() => {
    refreshSessions().catch(() => {
      setSessions([]);
      setCurrentSessionId('');
      setMessages([]);
    });
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
      const r = await api.ask(text, userId, currentSessionId);
      setMessages((v) => [...v, { role: 'assistant', content: r.reply, meta: { model: r.model, reason: r.reason } }]);
      refreshSessions().catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : '智能体调用失败');
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
    try {
      const r = await api.createChatSession(userId);
      setSessions(r.sessions || []);
      setCurrentSessionId(r.current_session_id || r.session_id);
      setMessages(r.messages || []);
      setInput('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '新建对话失败');
    }
  };

  const switchSession = async (sessionId: string) => {
    if (!sessionId || sessionId === currentSessionId || thinking) return;
    setError('');
    try {
      const r = await api.switchChatSession(sessionId, userId);
      setSessions(r.sessions || []);
      setCurrentSessionId(r.current_session_id || sessionId);
      setMessages(r.messages || []);
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换对话失败');
    }
  };

  const deleteSession = async () => {
    if (!currentSessionId || thinking) return;
    setError('');
    try {
      const r = await api.deleteChatSession(currentSessionId, userId);
      setSessions(r.sessions || []);
      setCurrentSessionId(r.current_session_id || '');
      setMessages(r.messages || []);
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
    setThinking(true);
    setError('');
    try {
      const r = await api.retryMessage(editingId, text, userId, currentSessionId);
      setMessages(r.messages || []);
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
    setUploading(true);
    setError('');
    try {
      const r = await api.uploadFiles(files, userId);
      const summary = r.messages.join('\n\n');
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
    setThinking(true);
    setError('');
    const prompt = '一键检查并运行闪电河流域土壤水分融合论文流程。';
    setMessages((v) => [...v, { role: 'user', content: prompt }]);
    try {
      const r = await api.runSoilMoistureWorkflow(userId);
      setMessages((v) => [...v, { role: 'assistant', content: r.reply, meta: { model: r.model, reason: r.reason } }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '论文流程启动失败');
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
                className="min-w-0 flex-1 rounded-2xl border border-white/30 bg-white/50 px-3 py-2 text-xs font-semibold outline-none dark:border-white/10 dark:bg-slate-900/50"
              >
                {sessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>{s.title || '新对话'}</option>
                ))}
              </select>
              <button onClick={newSession} disabled={thinking} className="glass-button h-9 w-9 rounded-2xl p-0 disabled:opacity-60" title="新建对话"><Plus size={16} /></button>
              <button onClick={deleteSession} disabled={thinking || sessions.length <= 1} className="glass-button h-9 w-9 rounded-2xl p-0 text-coral disabled:opacity-40" title="删除当前对话"><Trash2 size={15} /></button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => fileInputRef.current?.click()} disabled={uploading} className="glass-button gap-2 rounded-2xl text-xs font-black disabled:opacity-60">
              <UploadCloud size={15} strokeWidth={1.7} /> {uploading ? '上传中...' : '上传数据'}
            </button>
            <button onClick={runThesisWorkflow} disabled={thinking} className="glass-button gap-2 rounded-2xl text-xs font-black disabled:opacity-60">
              <PlayCircle size={15} strokeWidth={1.7} /> 论文流程
            </button>
            <input
              ref={fileInputRef}
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
              <div className="space-y-2">
                {QUICK_PROMPTS.map((p) => (
                  <button key={p} onClick={() => sendPrompt(p)} className="block w-full rounded-2xl border border-white/30 bg-white/35 px-3 py-2 text-left text-xs leading-5 transition hover:bg-white/60 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10">
                    {p}
                  </button>
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
                        <MarkdownMessage content={m.content} />
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
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="输入数据下载、融合建模、精度验证、制图或结果追问..."
              className="max-h-28 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-400"
            />
            <button onClick={send} disabled={thinking || !input.trim()} className="primary-button h-10 w-10 shrink-0 rounded-2xl p-0 disabled:opacity-45"><SendHorizontal size={18} strokeWidth={1.5} /></button>
          </div>
        </div>
        <div {...dragHandle} className="absolute right-0 top-0 h-full w-2 cursor-ew-resize" />
      </GlassCard>
    </motion.aside>
  );
}
