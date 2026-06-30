import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type RealtimeChatEvent } from '@/lib/api';
import { createRealtimeEventGateState, shouldAcceptRealtimeEvent, type RealtimeEventGateState } from './chatRealtimeEventModel';

export type RealtimeSyncState = 'connecting' | 'live' | 'polling';

type UseChatRealtimeEventsArgs = {
  userId: string;
  sessionId: string;
  onEvent: (event: RealtimeChatEvent, realtimeSyncState: RealtimeSyncState) => void;
};

const REALTIME_EVENT_TYPES: RealtimeChatEvent['kind'][] = [
  'task_status',
  'task_progress',
  'task_result',
  'model_token',
  'model_complete',
  'warning',
  'error',
];

export function useChatRealtimeEvents({ userId, sessionId, onEvent }: UseChatRealtimeEventsArgs) {
  const [realtimeSyncState, setRealtimeSyncState] = useState<RealtimeSyncState>('polling');
  const sourceRef = useRef<EventSource | null>(null);
  const eventGateRef = useRef<RealtimeEventGateState>(createRealtimeEventGateState());
  const syncStateRef = useRef<RealtimeSyncState>('polling');

  const setSyncState = useCallback((state: RealtimeSyncState) => {
    syncStateRef.current = state;
    setRealtimeSyncState(state);
  }, []);

  const applyRealtimeEvent = useCallback((event: RealtimeChatEvent) => {
    if (!shouldAcceptRealtimeEvent(event, eventGateRef.current)) return;
    onEvent(event, syncStateRef.current);
  }, [onEvent]);

  useEffect(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    eventGateRef.current = createRealtimeEventGateState();
    if (!userId || !sessionId) {
      setSyncState('polling');
      return;
    }
    let disposed = false;
    setSyncState('connecting');
    const receive = (event: RealtimeChatEvent) => {
      if (!disposed) applyRealtimeEvent(event);
    };
    api.replayChatEvents(userId, sessionId, 0)
      .then((result) => result.events.forEach(receive))
      .catch(() => {
        if (!disposed) setSyncState('polling');
      });
    const source = api.openChatEventStream(userId, sessionId, 0);
    sourceRef.current = source;
    const handle = (raw: MessageEvent<string>) => {
      try {
        receive(JSON.parse(raw.data) as RealtimeChatEvent);
      } catch {}
    };
    REALTIME_EVENT_TYPES.forEach((type) => source.addEventListener(type, handle as EventListener));
    source.onopen = () => {
      if (!disposed) setSyncState('live');
    };
    source.onerror = () => {
      if (!disposed) setSyncState('polling');
    };
    return () => {
      disposed = true;
      REALTIME_EVENT_TYPES.forEach((type) => source.removeEventListener(type, handle as EventListener));
      source.close();
      if (sourceRef.current === source) sourceRef.current = null;
    };
  }, [applyRealtimeEvent, sessionId, setSyncState, userId]);

  return { realtimeSyncState, applyRealtimeEvent };
}
