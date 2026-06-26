import type { ChatMessage } from '@/lib/api';

export type TaskSummaryStatus = 'planning' | 'queued' | 'running' | 'awaiting_confirmation' | 'waiting_login' | 'paused' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';

export type ChatTaskSummaryItem = {
  id: string;
  title: string;
  summary: string;
  status: TaskSummaryStatus;
  progress: number | null;
  currentStep: string;
  syncState: string;
  updatedAt: string;
};

const SENSITIVE_PATTERNS = [
  /[A-Za-z]:\\[^\s'"<>]+/g,
  /\/(?:Users|home|var|tmp|etc|root)\/[^\s'"<>]+/g,
  /\.env\b/gi,
  /token\s*=\s*[^\s'"<>]+/gi,
  /cookie\b/gi,
  /storage_state(?:\.json)?/gi,
  /Traceback[\s\S]*?(?=$|\n\n)/g,
];

export function hashString(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
}

export function messageKey(message: ChatMessage) {
  if (message.id) return `message-${message.id}`;
  if (message.message_id) return `message-${message.message_id}`;
  const stableParts = [message.role, message.created_at || '', message.session_id || '', String(message.content || '').length, hashString(message.content || '')];
  return `message-${stableParts.join('-')}`;
}

export function messageIsToolTask(message: ChatMessage) {
  const meta = message.meta || {};
  const mode = String(meta.mode || '');
  const actionType = String(meta.action_required?.type || '');
  const interactionType = String(meta.interaction_type || '');
  const reason = String(meta.reason || '');
  return reason !== 'tool_mode_required' && (
    interactionType === 'tool_task'
    || Boolean(meta.task_card)
    || Boolean(meta.management_view)
    || Boolean(meta.download_management_view)
    || ['background_worker', 'validated_download_executor', 'coordinated_workflow', 'validated_workflow_executor', 'validated_tool_executor'].includes(mode)
    || ['confirmation_required', 'login_required'].includes(actionType)
  );
}

export function buildRenderMessages(messages: ChatMessage[]) {
  const byKey = new Map<string, ChatMessage>();
  messages.forEach((message) => {
    const key = messageKey(message);
    const existing = byKey.get(key);
    byKey.set(key, existing
      ? {
          ...existing,
          ...message,
          content: message.content || existing.content,
          meta: { ...(existing.meta || {}), ...(message.meta || {}) },
        }
      : message);
  });
  return Array.from(byKey.values());
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function sanitizeText(value: unknown, fallback = '') {
  let text = String(value || '').trim();
  if (!text) return fallback;
  let redacted = false;
  SENSITIVE_PATTERNS.forEach((pattern) => {
    if (pattern.test(text)) {
      redacted = true;
      text = text.replace(pattern, '敏感细节已隐藏');
    }
    pattern.lastIndex = 0;
  });
  text = text.replace(/\s+/g, ' ').trim();
  if (!text) return fallback;
  return redacted && !/敏感细节已隐藏|Sensitive details hidden/.test(text) ? `${text} · 敏感细节已隐藏` : text;
}

function normalizeStatus(value: unknown): TaskSummaryStatus {
  const status = String(value || '').toLowerCase();
  if (['planning', 'queued', 'running', 'awaiting_confirmation', 'waiting_login', 'paused', 'succeeded', 'failed', 'cancelled'].includes(status)) {
    return status as TaskSummaryStatus;
  }
  if (status === 'success' || status === 'completed' || status === 'complete') return 'succeeded';
  if (status === 'error') return 'failed';
  return 'unknown';
}

function numberFrom(value: unknown): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function taskIdFromMessage(message: ChatMessage) {
  const meta = message.meta || {};
  const action = record(meta.action_required);
  const management = record(meta.management_view || meta.download_management_view);
  const card = record(meta.task_card);
  return String(
    meta.task_id
    || meta.job_id
    || card.task_id
    || management.task_id
    || management.job_id
    || action.job_id
    || message.id
    || message.message_id
    || messageKey(message)
  );
}

export function buildChatTaskSummary(messages: ChatMessage[]): ChatTaskSummaryItem[] {
  return buildRenderMessages(messages)
    .filter((message) => message.role === 'assistant' && messageIsToolTask(message))
    .map((message) => {
      const meta = message.meta || {};
      const card = record(meta.task_card);
      const management = record(meta.management_view || meta.download_management_view);
      const execution = record(meta.execution_summary);
      const action = record(meta.action_required);
      const title = sanitizeText(
        card.title || management.title || management.name || action.message || meta.title || 'GIS task',
        'GIS task'
      );
      const currentStep = sanitizeText(
        meta.current_step || card.current_step || management.current_step || management.action_state || '',
        ''
      );
      const summary = sanitizeText(
        execution.summary || management.user_message || card.summary || currentStep || message.content || title,
        title
      );
      const status = normalizeStatus(meta.status || card.status || management.status || action.type);
      return {
        id: taskIdFromMessage(message),
        title,
        summary,
        status,
        progress: numberFrom(meta.progress ?? card.progress ?? management.progress),
        currentStep,
        syncState: String(meta.realtime_sync || ''),
        updatedAt: String(meta.heartbeat_at || meta.updated_at || meta.started_at || message.created_at || ''),
      };
    })
    .slice(-6)
    .reverse();
}
