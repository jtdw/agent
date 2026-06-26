type UseChatPromptPreparationArgs = {
  thinking: boolean;
  userId: string;
  setInput: (value: string) => void;
  setError: (message: string) => void;
};

export function useChatPromptPreparation({
  thinking,
  userId,
  setInput,
  setError,
}: UseChatPromptPreparationArgs) {
  const preparePrompt = (prompt: string) => {
    const text = prompt.trim();
    if (!text || thinking) return null;
    if (!userId) {
      setError('请先登录账号，再使用智能助手对话。');
      return null;
    }
    setInput('');
    setError('');
    return text;
  };

  return { preparePrompt };
}
