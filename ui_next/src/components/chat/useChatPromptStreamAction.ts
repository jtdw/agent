import { api, type ChatMessage, type RealtimeChatEvent } from '@/lib/api';
import type { ChatContextPayload } from '@/lib/chatContext';
import { assistantErrorContent } from '../chatMessageContent';
import { buildSendPromptDraft, buildStreamChatContext } from './chatSendModel';
import type { RealtimeSyncState } from './useChatRealtimeEvents';
import type { useChatStreamLifecycle } from './useChatStreamLifecycle';

type StreamLifecycle = ReturnType<typeof useChatStreamLifecycle>;

type UseChatPromptStreamActionArgs = {
  userId: string;
  currentSessionId: string;
  currentInteractionMode: 'chat_only' | 'tool_enabled';
  chatContext: ChatContextPayload;
  realtimeSyncState: RealtimeSyncState;
  streamLifecycle: StreamLifecycle;
  applyRealtimeEvent: (event: RealtimeChatEvent) => void;
  setMessages: (updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
  setLastFailedPrompt: (prompt: string) => void;
  setError: (message: string) => void;
  refreshSessions: () => Promise<void>;
  messageMatchesJob: (message: ChatMessage, jobId: string) => boolean;
  mergeTaskCardUpdate: (
    current: ChatMessage[],
    matcher: (message: ChatMessage) => boolean,
    update: ChatMessage
  ) => ChatMessage[];
};

export function useChatPromptStreamAction({
  userId,
  currentSessionId,
  currentInteractionMode,
  chatContext,
  realtimeSyncState,
  streamLifecycle,
  applyRealtimeEvent,
  setMessages,
  setLastFailedPrompt,
  setError,
  refreshSessions,
  messageMatchesJob,
  mergeTaskCardUpdate,
}: UseChatPromptStreamActionArgs) {
  const streamPrompt = async (text: string) => {
    const draft = buildSendPromptDraft({ text, realtimeSyncState, interactionMode: currentInteractionMode });
    const controller = new AbortController();
    const { taskId, optimisticUserMessage, streamingAssistantMessage } = draft;
    setMessages((messages) => [...messages, optimisticUserMessage, streamingAssistantMessage]);
    streamLifecycle.startTask(taskId, controller);
    try {
      await api.streamChat(
        text,
        userId,
        currentSessionId,
        buildStreamChatContext(chatContext, currentSessionId),
        { onEvent: applyRealtimeEvent },
        controller.signal,
        taskId,
      );
      setLastFailedPrompt('');
      refreshSessions().catch(() => {});
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      const content = assistantErrorContent(error);
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, taskId), {
        role: 'assistant',
        content,
        meta: { task_id: taskId, reason: 'error', status: 'failed', streaming: false },
      }));
      setLastFailedPrompt(text);
      setError('');
    } finally {
      streamLifecycle.finishTask(taskId, controller);
    }
  };

  return { streamPrompt };
}
