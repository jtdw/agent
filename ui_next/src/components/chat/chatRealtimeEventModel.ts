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

const CHAT_COMPLETION_TRANSIENT_KEYS = [
  'task_id',
  'job_id',
  'status',
  'progress',
  'phase',
  'current_step',
  'heartbeat_at',
  'started_at',
  'elapsed_ms',
  'timeout_reason',
] as const;

const GENERIC_TASK_STATUS_KEYS = [
  'job_id',
  'status',
  'progress',
  'phase',
  'current_step',
  'heartbeat_at',
  'started_at',
  'elapsed_ms',
  'timeout_reason',
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

function hasToolTaskMarkers(meta: Record<string, unknown>) {
  const interactionType = String(meta.interaction_type || '');
  const mode = String(meta.mode || '');
  const action = meta.action_required && typeof meta.action_required === 'object'
    ? meta.action_required as Record<string, unknown>
    : {};
  return interactionType === 'tool_task'
    || Boolean(meta.task_card)
    || Boolean(meta.management_view)
    || Boolean(meta.download_management_view)
    || ['background_worker', 'validated_download_executor', 'coordinated_workflow', 'validated_workflow_executor', 'validated_tool_executor'].includes(mode)
    || ['confirmation_required', 'login_required'].includes(String(action.type || ''));
}

function isGenericTaskStatusForChatPlaceholder(
  existingMeta: Record<string, unknown>,
  eventMeta: Record<string, unknown>,
  event: Pick<RealtimeChatEvent, 'kind'>
) {
  return (
    (event.kind === 'task_status' || event.kind === 'task_progress')
    && !hasToolTaskMarkers(existingMeta)
    && !hasToolTaskMarkers(eventMeta)
  );
}

export function shouldUseRealtimeEventContent(
  existingMeta: Record<string, unknown>,
  eventMeta: Record<string, unknown>,
  event: Pick<RealtimeChatEvent, 'kind'>
) {
  return !isGenericTaskStatusForChatPlaceholder(existingMeta, eventMeta, event);
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
  const genericTaskStatusForChatPlaceholder = isGenericTaskStatusForChatPlaceholder(existingMeta, eventMeta, event);
  const next = { ...existingMeta, ...eventMeta };
  if (genericTaskStatusForChatPlaceholder) {
    GENERIC_TASK_STATUS_KEYS.forEach((key) => {
      delete next[key];
    });
  }
  if (isChatCompletion) {
    TOOL_TASK_META_KEYS.forEach((key) => {
      delete next[key];
    });
    CHAT_COMPLETION_TRANSIENT_KEYS.forEach((key) => {
      delete next[key];
    });
  }
  return next;
}
