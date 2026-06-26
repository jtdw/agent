import { api, type ChatMessage } from '@/lib/api';
import { assistantErrorContent, assistantReplyContent } from '../chatMessageContent';
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
};

export function useChatThesisWorkflow({
  thinking,
  userId,
  currentSessionId,
  streamLifecycle,
  setError,
  setMessages,
  setLastFailedPrompt,
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
      setMessages((messages) => [
        ...messages,
        {
          role: 'assistant',
          content: assistantReplyContent(response.reply),
          meta: { model: response.model, reason: response.reason },
        },
      ]);
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
