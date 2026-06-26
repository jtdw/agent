import { api, type ChatMessage } from '@/lib/api';
import type { ChatContextPayload } from '@/lib/chatContext';
import { assistantErrorContent } from '../chatMessageContent';
import { hashString } from './chatWorkspaceModel';
import type { useChatStreamLifecycle } from './useChatStreamLifecycle';

type StreamLifecycle = ReturnType<typeof useChatStreamLifecycle>;
type ConfirmationResponse = Awaited<ReturnType<typeof api.confirmChatAction>>;

type UseChatConfirmationActionArgs = {
  thinking: boolean;
  userId: string;
  currentSessionId: string;
  chatContext: ChatContextPayload;
  streamLifecycle: StreamLifecycle;
  setError: (message: string) => void;
  setMessages: (updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
  onConfirmationComplete: (token: string, response: ConfirmationResponse) => void;
};

export function useChatConfirmationAction({
  thinking,
  userId,
  currentSessionId,
  chatContext,
  streamLifecycle,
  setError,
  setMessages,
  onConfirmationComplete,
}: UseChatConfirmationActionArgs) {
  const confirmAction = async (confirmationPrompt: string, confirmedActionId: string) => {
    const prompt = confirmationPrompt.trim();
    const token = confirmedActionId.trim();
    if (!token || thinking) return;
    if (!userId) {
      setError('请先登录账号，再确认执行。');
      return;
    }
    setError('');
    const controller = new AbortController();
    const taskId = `chat_confirm_${Date.now()}_${hashString(token)}`;
    streamLifecycle.startTask(taskId, controller);
    try {
      const response = await api.confirmChatAction(
        token,
        prompt || '确认执行',
        userId,
        currentSessionId,
        { ...chatContext, session_id: currentSessionId },
        controller.signal,
        taskId,
      );
      onConfirmationComplete(token, response);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      const content = assistantErrorContent(error);
      setMessages((messages) => [...messages, { role: 'assistant', content, meta: { reason: 'error' } }]);
      setError('');
    } finally {
      streamLifecycle.finishTask(taskId, controller);
    }
  };

  return { confirmAction };
}
