import type { ChatMessage } from '@/lib/api';
import type { ChatContextPayload } from '@/lib/chatContext';
import { hashString } from './chatWorkspaceModel';

type BuildSendPromptDraftArgs = {
  text: string;
  realtimeSyncState: 'connecting' | 'live' | 'polling';
  now?: number;
};

export function buildSendPromptDraft({ text, realtimeSyncState, now = Date.now() }: BuildSendPromptDraftArgs) {
  const normalizedText = text.trim();
  const textHash = hashString(normalizedText);
  const optimisticUserMessage: ChatMessage = {
    id: `pending-${now}-${textHash}`,
    role: 'user',
    content: normalizedText,
  };
  const taskId = `chat_${now}_${textHash}`;
  const streamingAssistantMessage: ChatMessage = {
    id: `stream-${taskId}`,
    role: 'assistant',
    content: '',
    meta: {
      task_id: taskId,
      status: 'planning',
      streaming: true,
      realtime_sync: realtimeSyncState,
    },
  };
  return {
    text: normalizedText,
    taskId,
    optimisticUserMessage,
    streamingAssistantMessage,
  };
}

export function buildStreamChatContext(chatContext: ChatContextPayload, sessionId: string): ChatContextPayload {
  return { ...chatContext, session_id: sessionId };
}
