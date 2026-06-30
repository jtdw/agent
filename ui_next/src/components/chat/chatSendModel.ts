import type { ChatMessage } from '@/lib/api';
import type { ChatContextPayload } from '@/lib/chatContext';
import { hashString } from './chatWorkspaceModel';

type BuildSendPromptDraftArgs = {
  text: string;
  realtimeSyncState: 'connecting' | 'live' | 'polling';
  interactionMode?: 'chat_only' | 'tool_enabled';
  now?: number;
};

function looksLikeToolTask(text: string) {
  const value = text.toLowerCase();
  return [
    '下载',
    '获取',
    '导入',
    '上传',
    '裁剪',
    '叠加',
    '重投影',
    '制图',
    '出图',
    '建模',
    '训练',
    'dem',
    'ndvi',
    'evi',
    'landsat',
    'sentinel',
    'clip',
    'map',
    'model',
  ].some((token) => value.includes(token));
}

export function buildSendPromptDraft({ text, realtimeSyncState, interactionMode = 'chat_only', now = Date.now() }: BuildSendPromptDraftArgs) {
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
      streaming: true,
      realtime_sync: realtimeSyncState,
    },
  };
  if (interactionMode === 'tool_enabled' && looksLikeToolTask(normalizedText)) {
    streamingAssistantMessage.meta = {
      ...streamingAssistantMessage.meta,
      interaction_type: 'tool_task',
      mode: 'optimistic_tool_task',
      status: 'planning',
      task_card: {
        task_id: taskId,
        status: 'planning',
        progress: 3,
        current_step: '接收任务',
        summary: '正在准备 GIS 任务。',
      },
    };
  }
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
