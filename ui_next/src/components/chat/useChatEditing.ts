import { useState } from 'react';
import { api, type ChatMessage } from '@/lib/api';
import { buildRetryEditedMessageDraft } from './chatActionModel';

type RetryMessageResponse = Awaited<ReturnType<typeof api.retryMessage>>;

type ChatEditingLifecycle = {
  startBusy: () => void;
  finishBusy: () => void;
};

type UseChatEditingArgs = {
  thinking: boolean;
  userId: string;
  currentSessionId: string;
  streamLifecycle: ChatEditingLifecycle;
  setError: (message: string) => void;
  onRetryComplete: (response: RetryMessageResponse) => void;
};

export function useChatEditing({
  thinking,
  userId,
  currentSessionId,
  streamLifecycle,
  setError,
  onRetryComplete,
}: UseChatEditingArgs) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState('');

  const beginEdit = (message: ChatMessage) => {
    if (!message.message_id || thinking) return;
    setEditingId(message.message_id);
    setEditText(message.content);
  };

  const cancelEdit = () => setEditingId(null);

  const retryEditedMessage = async () => {
    if (thinking) return;
    const draft = buildRetryEditedMessageDraft(editingId, editText);
    if (!draft) return;
    if (!userId) {
      setError('\u8bf7\u5148\u767b\u5f55\u8d26\u53f7\uff0c\u518d\u91cd\u65b0\u751f\u6210\u56de\u7b54\u3002');
      return;
    }
    streamLifecycle.startBusy();
    setError('');
    try {
      const response = await api.retryMessage(draft.messageId, draft.text, userId, currentSessionId);
      onRetryComplete(response);
      setEditingId(null);
      setEditText('');
    } catch (error) {
      setError(error instanceof Error ? error.message : '\u91cd\u65b0\u751f\u6210\u5931\u8d25');
    } finally {
      streamLifecycle.finishBusy();
    }
  };

  return {
    editingId,
    editText,
    setEditText,
    beginEdit,
    cancelEdit,
    retryEditedMessage,
  };
}
