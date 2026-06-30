import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import type { ChatSession } from '@/lib/api';
import { cn } from '@/lib/cn';
import { sidebarDisplaySessions } from './chatSessionModel';

type ChatSessionSidebarProps = {
  currentSessionId: string;
  visibleSessions: ChatSession[];
  messagesLength: number;
  thinking: boolean;
  modelLoading: boolean;
  userId: string;
  switchSession: (sessionId: string) => void;
  newSession: () => void;
  deleteSession: () => void;
};

function sessionDate(session: ChatSession) {
  const value = session.updated_at || session.created_at;
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date);
}

export function ChatSessionSidebar({
  currentSessionId,
  visibleSessions,
  messagesLength,
  thinking,
  modelLoading,
  userId,
  switchSession,
  newSession,
  deleteSession,
}: ChatSessionSidebarProps) {
  const displaySessions = sidebarDisplaySessions({ visibleSessions, currentSessionId, messagesLength });

  return (
    <aside data-testid="chat-session-list" className="chat-session-rail lg:col-start-1 lg:row-span-3 lg:row-start-1">
      <button data-testid="chat-new-session" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-primary-action chat-session-new-action w-full">
        <Plus size={16} strokeWidth={2} />
        <span>新建对话</span>
      </button>
      <div className="mt-5 flex items-center justify-between px-2 text-[11px] font-bold uppercase tracking-[0.08em] text-slate-400">
        <span>最近对话</span><span className="chat-session-count-pill">{displaySessions.length}</span>
      </div>
      <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
        {displaySessions.map((session) => {
          const isLocalCurrent = !session.session_id && !currentSessionId;
          const active = session.session_id === currentSessionId || isLocalCurrent;
          const canSwitch = Boolean(session.session_id);
          return (
            <button
              key={session.session_id || 'local-current-session'}
              onClick={() => {
                if (canSwitch) switchSession(session.session_id);
              }}
              disabled={thinking || modelLoading || !canSwitch}
              className={cn('chat-session-row group', active && 'is-active')}
            >
              <MessageSquare size={15} strokeWidth={1.7} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 text-left">
                <span className="block truncate font-semibold">{session.title || '新对话'}</span>
                <span className="mt-1 block text-[10px] font-medium opacity-60">{sessionDate(session) || (active ? `${messagesLength} 条消息` : '历史对话')}</span>
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
  );
}
