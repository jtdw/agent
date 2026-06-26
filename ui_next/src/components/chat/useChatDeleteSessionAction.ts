import { api } from '@/lib/api';

type DeleteSessionResponse = Awaited<ReturnType<typeof api.deleteChatSession>>;
type ClearSessionResponse = Awaited<ReturnType<typeof api.clearChatSession>>;
type DeleteOrClearSessionResponse = DeleteSessionResponse | ClearSessionResponse;

type UseChatDeleteSessionActionArgs = {
  thinking: boolean;
  userId: string;
  currentSessionId: string;
  sessionCount: number;
  setError: (message: string) => void;
  confirmDelete?: (message: string) => boolean;
  onSessionDeleted: (response: DeleteOrClearSessionResponse) => void;
};

export function useChatDeleteSessionAction({
  thinking,
  userId,
  currentSessionId,
  sessionCount,
  setError,
  confirmDelete = (message) => window.confirm(message),
  onSessionDeleted,
}: UseChatDeleteSessionActionArgs) {
  const deleteSession = async () => {
    if (!currentSessionId || thinking) return;
    setError('');
    if (!userId) {
      setError('请先登录账号，再管理对话。');
      return;
    }
    if (!confirmDelete('删除当前对话？删除后该对话的聊天记录和会话级数据将不可恢复。')) return;
    try {
      const response = sessionCount > 1
        ? await api.deleteChatSession(currentSessionId, userId)
        : await api.clearChatSession(currentSessionId, userId);
      onSessionDeleted(response);
    } catch (error) {
      setError(error instanceof Error ? error.message : '删除对话失败');
    }
  };

  return { deleteSession };
}
