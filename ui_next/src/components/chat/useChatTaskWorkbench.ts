import { useMemo } from 'react';
import type { ChatMessage } from '@/lib/api';
import { buildChatTaskSummary, buildRenderMessages } from './chatWorkspaceModel';

export function useChatTaskWorkbench(messages: ChatMessage[]) {
  return useMemo(() => ({
    renderMessages: buildRenderMessages(messages),
    taskSummaryItems: buildChatTaskSummary(messages),
  }), [messages]);
}
