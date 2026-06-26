import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, type ChatModelState } from '@/lib/api';

type UseChatModelsArgs = {
  userId: string;
  sessionId: string;
};

export function useChatModels({ userId, sessionId }: UseChatModelsArgs) {
  const [chatModels, setChatModels] = useState<ChatModelState | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelNotice, setModelNotice] = useState('');
  const [modelError, setModelError] = useState('');
  const noticeTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);

  const visibleModels = useMemo(() => {
    const byId = new Map<string, NonNullable<ChatModelState['models']>[number]>();
    (chatModels?.models || []).forEach((model) => {
      const id = String(model.id || '').trim();
      if (id) byId.set(id, model);
    });
    return Array.from(byId.values());
  }, [chatModels?.models]);

  const clearNoticeTimer = useCallback(() => {
    if (!noticeTimerRef.current) return;
    window.clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = null;
  }, []);

  useEffect(() => {
    setModelNotice('');
    setModelError('');
    clearNoticeTimer();
    if (!userId || !sessionId) {
      setChatModels(null);
      setModelLoading(false);
      return;
    }

    let active = true;
    setModelLoading(true);
    api.chatModels(userId, sessionId)
      .then((result) => {
        if (active) setChatModels(result);
      })
      .catch((cause) => {
        if (active) setModelError(cause instanceof Error ? cause.message : '模型列表加载失败');
      })
      .finally(() => {
        if (active) setModelLoading(false);
      });

    return () => {
      active = false;
    };
  }, [clearNoticeTimer, userId, sessionId]);

  useEffect(() => () => clearNoticeTimer(), [clearNoticeTimer]);

  const changeChatModel = useCallback(async (model: string) => {
    if (!userId || !sessionId || modelLoading) return;
    const previous = chatModels;
    setModelLoading(true);
    setModelNotice('');
    setModelError('');
    clearNoticeTimer();
    try {
      const result = await api.selectChatModel(model, userId, sessionId);
      setChatModels(result);
      setModelNotice('已切换');
      noticeTimerRef.current = window.setTimeout(() => {
        setModelNotice('');
        noticeTimerRef.current = null;
      }, 1800);
    } catch (cause) {
      setChatModels(previous);
      setModelError(cause instanceof Error ? cause.message : '模型切换失败');
    } finally {
      setModelLoading(false);
    }
  }, [chatModels, clearNoticeTimer, modelLoading, sessionId, userId]);

  return {
    chatModels,
    visibleModels,
    modelLoading,
    modelNotice,
    modelError,
    changeChatModel,
  };
}
