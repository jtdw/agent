import { api } from '@/lib/api';

export type ChatInteractionMode = 'chat_only' | 'tool_enabled';

type InteractionModeResponse = Awaited<ReturnType<typeof api.setChatInteractionMode>>;

type UseChatInteractionModeActionArgs = {
  thinking: boolean;
  userId: string;
  currentSessionId: string;
  currentInteractionMode: ChatInteractionMode;
  setError: (message: string) => void;
  onModeChanged: (response: InteractionModeResponse) => void;
};

export function useChatInteractionModeAction({
  thinking,
  userId,
  currentSessionId,
  currentInteractionMode,
  setError,
  onModeChanged,
}: UseChatInteractionModeActionArgs) {
  const setInteractionMode = async (mode: ChatInteractionMode) => {
    if (!currentSessionId || mode === currentInteractionMode || thinking) return;
    if (!userId) {
      setError('请先登录账号，再切换会话模式。');
      return;
    }
    setError('');
    try {
      const response = await api.setChatInteractionMode(currentSessionId, mode, userId);
      onModeChanged(response);
    } catch (error) {
      setError(error instanceof Error ? error.message : '切换会话模式失败');
    }
  };

  return { setInteractionMode };
}
