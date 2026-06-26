import { api } from '@/lib/api';

type NewSessionResponse = Awaited<ReturnType<typeof api.createChatSession>>;

type UseChatNewSessionActionArgs = {
  thinking: boolean;
  userId: string;
  setError: (message: string) => void;
  onSessionCreated: (response: NewSessionResponse) => void;
};

export function useChatNewSessionAction({
  thinking,
  userId,
  setError,
  onSessionCreated,
}: UseChatNewSessionActionArgs) {
  const newSession = async () => {
    if (thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再新建对话。');
      return;
    }
    try {
      const response = await api.createChatSession(userId);
      onSessionCreated(response);
    } catch (error) {
      setError(error instanceof Error ? error.message : '新建对话失败');
    }
  };

  return { newSession };
}
