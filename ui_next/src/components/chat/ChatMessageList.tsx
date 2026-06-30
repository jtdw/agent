import type { RefObject, UIEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, Check, FileUp, Pencil, RefreshCcw, Sparkles, X } from 'lucide-react';
import type { ChatMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { assistantReplyContent } from '../chatMessageContent';
import { ChatMessageRenderer } from '../ChatMessageRenderer';
import { UploadResultCard } from '../UploadResultCard';
import { messageIsToolTask, messageKey } from './chatWorkspaceModel';

export type ChatPromptGroup = {
  title: string;
  description: string;
  icon: LucideIcon;
  prompt: string;
};

type ChatMessageListProps = {
  isPage: boolean;
  listRef: RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  renderMessages: ChatMessage[];
  promptGroups: ChatPromptGroup[];
  sendPrompt: (prompt: string) => void;
  editingId: number | null;
  editText: string;
  setEditText: (value: string) => void;
  cancelEdit: () => void;
  retryEditedMessage: () => void;
  beginEdit: (message: ChatMessage) => void;
  resumeReadyJobIds: Set<string>;
  openGSCloudLogin: (jobId: string) => void;
  resumeDownload: (jobId: string) => void;
  cancelDownload: (jobId: string) => void;
  retryDownload: (jobId: string) => void;
  chooseClarification: (value: string, label: string) => void;
  confirmAction: (prompt: string, confirmedActionId: string) => void;
  currentSessionId: string;
  lastFailedPrompt: string;
  thinking: boolean;
  currentInteractionMode: 'chat_only' | 'tool_enabled';
  error: string;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
};

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
      <div className="mt-3 grid gap-1.5">
        {steps.map((step, idx) => (
          <div key={step} className="flex items-center gap-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
            <span className={cn('h-1.5 w-1.5 rounded-full', idx === 0 ? 'bg-cyan-glow' : 'bg-slate-300 dark:bg-slate-600')} />
            {step}
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

export function ChatMessageList({
  isPage,
  listRef,
  messages,
  renderMessages,
  promptGroups,
  sendPrompt,
  editingId,
  editText,
  setEditText,
  cancelEdit,
  retryEditedMessage,
  beginEdit,
  resumeReadyJobIds,
  openGSCloudLogin,
  resumeDownload,
  cancelDownload,
  retryDownload,
  chooseClarification,
  confirmAction,
  currentSessionId,
  lastFailedPrompt,
  thinking,
  currentInteractionMode,
  error,
  onScroll,
}: ChatMessageListProps) {
  return (
    <div
      ref={listRef}
      onScroll={onScroll}
      className={cn('chat-scroll relative flex-1 space-y-4 overflow-y-auto bg-gradient-to-b from-slate-50/35 to-white/35 px-4 pb-24 pt-5 lg:pb-5 dark:from-slate-950/20 dark:to-slate-900/20', isPage && 'min-h-0 px-6 lg:col-start-2 lg:row-start-2')}
    >
      {messages.length === 0 && (
        <div data-testid="chat-empty-state" className="mx-auto flex min-h-full max-w-3xl flex-col justify-center py-8">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 text-blue-600 shadow-inner dark:from-blue-950/50 dark:to-cyan-950/30 dark:text-cyan-300"><Sparkles size={20} strokeWidth={1.8} /></div>
            <div><h2 className="text-xl font-bold tracking-tight text-slate-950 dark:text-slate-50">今天想处理什么？</h2><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">直接描述目标，我会结合当前工作区完成 GIS 任务。</p></div>
          </div>
          <div className="mt-7 grid gap-3 sm:grid-cols-2">
            {promptGroups.map((group) => {
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
                !isUser && !isToolTask && 'rounded-[22px] px-4 py-3 shadow-[0_14px_32px_rgba(15,23,42,.09)]',
                isUser && !isEditing && 'chat-user-bubble max-w-[min(72%,36rem)] rounded-[20px] border border-slate-200/85 bg-white px-3.5 py-2.5 text-slate-900 shadow-sm dark:border-white/10 dark:bg-slate-900/80 dark:text-slate-100',
                isUser && isEditing && 'w-full max-w-[min(92%,54rem)] rounded-[22px] border border-slate-200/85 bg-white/96 px-4 py-3 text-slate-900 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/85 dark:text-slate-100',
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
                      className="chat-message-edit-textarea"
                    />
                    <div className="flex justify-end gap-2">
                      <button onClick={cancelEdit} className="rounded-xl border border-slate-200 bg-slate-50 p-2 text-slate-600 transition hover:bg-slate-100 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10" title="取消"><X size={15} /></button>
                      <button onClick={retryEditedMessage} className="rounded-xl bg-slate-950 p-2 text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white" title="保存并重新生成"><Check size={15} /></button>
                    </div>
                  </div>
                ) : (
                  <>
                    {!isUser && !isSystem && <MessageSourceBadge message={m} />}
                    {isSystem && Array.isArray(m.meta?.upload_summaries) && <UploadResultCard summaries={m.meta.upload_summaries} />}
                    <ChatMessageRenderer
                      message={m}
                      content={isUser || isSystem ? m.content : m.meta?.streaming ? m.content : assistantReplyContent(m.content)}
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
  );
}
