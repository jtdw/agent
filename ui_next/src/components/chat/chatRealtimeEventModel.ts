import type { RealtimeChatEvent } from '@/lib/api';

export const TRANSIENT_EVENT_VERSION_FLOOR = 1_000_000_000;

export type RealtimeEventGateState = {
  seenEventIds: Set<string>;
  latestPersistentVersion: number;
};

const TOOL_TASK_META_KEYS = [
  'action_required',
  'management_view',
  'download_management_view',
  'task_card',
] as const;

export function createRealtimeEventGateState(): RealtimeEventGateState {
  return {
    seenEventIds: new Set<string>(),
    latestPersistentVersion: 0,
  };
}

export function shouldAcceptRealtimeEvent(event: Pick<RealtimeChatEvent, 'event_id' | 'version' | 'kind'>, state: RealtimeEventGateState) {
  const eventId = String(event.event_id || '').trim();
  if (!eventId || state.seenEventIds.has(eventId)) return false;
  state.seenEventIds.add(eventId);
  if (state.seenEventIds.size > 800) {
    state.seenEventIds = new Set(Array.from(state.seenEventIds).slice(-400));
  }

  const version = Number(event.version || 0);
  if (version <= 0 || version >= TRANSIENT_EVENT_VERSION_FLOOR) return true;
  if (version <= state.latestPersistentVersion) return false;
  state.latestPersistentVersion = version;
  return true;
}

export function mergeRealtimeEventMeta(
  existingMeta: Record<string, unknown>,
  eventMeta: Record<string, unknown>,
  event: Pick<RealtimeChatEvent, 'kind'>
) {
  const interactionType = String(eventMeta.interaction_type || '');
  const mode = String(eventMeta.mode || '');
  const responseMode = String(eventMeta.response_mode || '');
  const isChatCompletion = event.kind === 'model_complete' && (
    interactionType === 'chat_answer'
    || mode === 'answer_only'
    || responseMode === 'answer_only'
  );
  const next = { ...existingMeta, ...eventMeta };
  if (isChatCompletion) {
    TOOL_TASK_META_KEYS.forEach((key) => {
      delete next[key];
    });
  }
  return next;
}
