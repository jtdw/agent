import { api } from '@/lib/api';

type SwitchSessionResponse = Awaited<ReturnType<typeof api.switchChatSession>>;

type UseChatSwitchSessionActionArgs = {
  thinking: boolean;
  modelLoading: boolean;
  userId: string;
  currentSessionId: string;
  setError: (message: string) => void;
  onSessionSwitched: (sessionId: string, response: SwitchSessionResponse) => void;
};

export function useChatSwitchSessionAction({
  thinking,
  modelLoading,
  userId,
  currentSessionId,
  setError,
  onSessionSwitched,
}: UseChatSwitchSessionActionArgs) {
  const switchSession = async (sessionId: string) => {
    if (!sessionId || sessionId === currentSessionId || thinking || modelLoading) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再切换对话。');
      return;
    }
    try {
      const response = await api.switchChatSession(sessionId, userId);
      onSessionSwitched(sessionId, response);
    } catch (error) {
      setError(error instanceof Error ? error.message : '切换对话失败');
    }
  };

  return { switchSession };
}
