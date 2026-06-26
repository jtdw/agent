import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, type ChatMessage, type ChatSession } from '@/lib/api';

type UseChatSessionsArgs = {
  userId: string;
  onSessionChange?: (sessionId: string) => void;
  onMessagesCleared: () => void;
  onMessagesRefreshed: (messages: ChatMessage[]) => void;
  onRefreshError: () => void;
};

export function useChatSessions({
  userId,
  onSessionChange,
  onMessagesCleared,
  onMessagesRefreshed,
  onRefreshError,
}: UseChatSessionsArgs) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState('');
  const sessionRefreshSeqRef = useRef(0);
  const lastKnownUserIdRef = useRef('');
  const lastSuccessfulSessionUserIdRef = useRef('');
  const latestUserIdRef = useRef('');
  const callbacksRef = useRef({ onSessionChange, onMessagesCleared, onMessagesRefreshed, onRefreshError });

  latestUserIdRef.current = userId;
  callbacksRef.current = { onSessionChange, onMessagesCleared, onMessagesRefreshed, onRefreshError };

  const visibleSessions = useMemo(() => {
    const byId = new Map<string, ChatSession>();
    sessions.forEach((session) => {
      const id = String(session.session_id || '').trim();
      if (id) byId.set(id, session);
    });
    return Array.from(byId.values());
  }, [sessions]);

  const currentSession = useMemo(
    () => visibleSessions.find((session) => session.session_id === currentSessionId) || null,
    [currentSessionId, visibleSessions]
  );

  const refreshSessions = useCallback(async () => {
    const requestedUserId = userId;
    const seq = ++sessionRefreshSeqRef.current;
    if (!requestedUserId) {
      if (lastKnownUserIdRef.current) {
        lastKnownUserIdRef.current = '';
        lastSuccessfulSessionUserIdRef.current = '';
      }
      setSessions([]);
      setCurrentSessionId('');
      callbacksRef.current.onSessionChange?.('');
      callbacksRef.current.onMessagesCleared();
      return;
    }

    lastKnownUserIdRef.current = requestedUserId;
    let result = await api.chatSessions(requestedUserId);
    if ((!result.sessions || result.sessions.length === 0) && result.current_session_id) {
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      if (seq === sessionRefreshSeqRef.current && latestUserIdRef.current === requestedUserId) {
        const retry = await api.chatSessions(requestedUserId);
        if ((retry.sessions || []).length > 0) result = retry;
      }
    }
    if (seq !== sessionRefreshSeqRef.current || latestUserIdRef.current !== requestedUserId) return;

    const nextSessions = (result.sessions || []).length > 0
      ? result.sessions || []
      : result.current_session_id
        ? [{ session_id: result.current_session_id, title: '新对话' }]
        : [];
    if (nextSessions.length === 0 && lastSuccessfulSessionUserIdRef.current === requestedUserId) return;

    setSessions(nextSessions);
    if (nextSessions.length > 0) lastSuccessfulSessionUserIdRef.current = requestedUserId;
    const nextSessionId = result.current_session_id || '';
    setCurrentSessionId(nextSessionId);
    callbacksRef.current.onSessionChange?.(nextSessionId);
    callbacksRef.current.onMessagesRefreshed(result.messages);
  }, [userId]);

  useEffect(() => {
    refreshSessions().catch(() => callbacksRef.current.onRefreshError());
  }, [refreshSessions]);

  return {
    sessions,
    setSessions,
    currentSessionId,
    setCurrentSessionId,
    visibleSessions,
    currentSession,
    refreshSessions,
  };
}
