import type { ChatMessage, ChatSession } from '@/lib/api';

type ChatSessionsResult = {
  sessions?: ChatSession[];
  current_session_id?: string;
  messages?: ChatMessage[];
};

type DeriveNextSessionStateArgs = {
  result: ChatSessionsResult;
  previousSessionId?: string;
};

type SidebarDisplaySessionsArgs = {
  visibleSessions: ChatSession[];
  currentSessionId: string;
  messagesLength: number;
};

function clean(value: unknown) {
  return String(value || '').trim();
}

function titleFromMessages(messages: ChatMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === 'user' && clean(message.content));
  const title = clean(firstUserMessage?.content).replace(/\s+/g, ' ');
  return title ? title.slice(0, 32) : '新对话';
}

function sessionIdFromMessages(messages: ChatMessage[]) {
  for (const message of messages) {
    const sessionId = clean(message.session_id);
    if (sessionId) return sessionId;
  }
  return '';
}

export function deriveNextSessionState({ result, previousSessionId = '' }: DeriveNextSessionStateArgs) {
  const sessions = Array.isArray(result.sessions) ? result.sessions : [];
  const messages = Array.isArray(result.messages) ? result.messages : [];
  const resultCurrentSessionId = clean(result.current_session_id);
  const previous = clean(previousSessionId);

  if (sessions.length > 0) {
    const ids = new Set(sessions.map((session) => clean(session.session_id)).filter(Boolean));
    const currentSessionId = resultCurrentSessionId && ids.has(resultCurrentSessionId)
      ? resultCurrentSessionId
      : previous && ids.has(previous)
        ? previous
        : clean(sessions[0]?.session_id);
    return { sessions, currentSessionId };
  }

  const fallbackSessionId = resultCurrentSessionId || sessionIdFromMessages(messages) || previous;
  if (!fallbackSessionId) return { sessions: [], currentSessionId: '' };

  return {
    sessions: [
      {
        session_id: fallbackSessionId,
        title: messages.length > 0 ? titleFromMessages(messages) : '新对话',
        message_count: messages.length,
      },
    ],
    currentSessionId: fallbackSessionId,
  };
}

export function sidebarDisplaySessions({ visibleSessions, currentSessionId, messagesLength }: SidebarDisplaySessionsArgs) {
  if (visibleSessions.length > 0) return visibleSessions;
  const sessionId = clean(currentSessionId);
  if (messagesLength <= 0) return [];
  return [
    {
      session_id: sessionId,
      title: '当前对话',
      message_count: messagesLength,
    },
  ];
}
