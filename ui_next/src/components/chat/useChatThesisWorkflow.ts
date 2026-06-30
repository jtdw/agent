import { api, type ChatMessage } from '@/lib/api';
import { assistantErrorContent, assistantReplyContent, normalizeChatMessages } from '../chatMessageContent';
import { THESIS_WORKFLOW_PROMPT } from './chatActionModel';

type ChatThesisWorkflowLifecycle = {
  startBusy: () => void;
  finishBusy: () => void;
};

type UseChatThesisWorkflowArgs = {
  thinking: boolean;
  userId: string;
  currentSessionId: string;
  streamLifecycle: ChatThesisWorkflowLifecycle;
  setError: (message: string) => void;
  setMessages: (updater: (current: ChatMessage[]) => ChatMessage[]) => void;
  setLastFailedPrompt: (prompt: string) => void;
  onWorkflowComplete: (response: Awaited<ReturnType<typeof api.runSoilMoistureWorkflow>>) => void;
};

export function useChatThesisWorkflow({
  thinking,
  userId,
  currentSessionId,
  streamLifecycle,
  setError,
  setMessages,
  setLastFailedPrompt,
  onWorkflowComplete,
}: UseChatThesisWorkflowArgs) {
  const runThesisWorkflow = async () => {
    if (thinking) return;
    if (!userId) {
      setError('请先登录账号，再运行论文流程。');
      return;
    }
    streamLifecycle.startBusy();
    setError('');
    const prompt = THESIS_WORKFLOW_PROMPT;
    setMessages((messages) => [...messages, { role: 'user', content: prompt }]);
    try {
      const response = await api.runSoilMoistureWorkflow(userId, currentSessionId);
      if (response.messages) {
        setMessages(() => normalizeChatMessages(response.messages));
      } else {
        setMessages((messages) => [
          ...messages,
          {
            role: 'assistant',
            content: assistantReplyContent(response.reply),
            meta: { model: response.model, reason: response.reason },
          },
        ]);
      }
      onWorkflowComplete(response);
      setLastFailedPrompt('');
    } catch (error) {
      const content = assistantErrorContent(error);
      setMessages((messages) => [...messages, { role: 'assistant', content, meta: { reason: 'error' } }]);
      setLastFailedPrompt(prompt);
      setError('');
    } finally {
      streamLifecycle.finishBusy();
    }
  };

  return { runThesisWorkflow };
}
