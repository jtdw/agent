import { useCallback, useRef, useState } from 'react';
import { api } from '@/lib/api';

type UseChatStreamLifecycleArgs = {
  userId: string;
  cancelReason?: string;
};

export function useChatStreamLifecycle({
  userId,
  cancelReason = '用户点击停止。',
}: UseChatStreamLifecycleArgs) {
  const [thinking, setThinking] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeTaskIdRef = useRef<string>('');

  const startBusy = useCallback(() => {
    setThinking(true);
  }, []);

  const finishBusy = useCallback(() => {
    setThinking(false);
  }, []);

  const startTask = useCallback((taskId: string, controller: AbortController) => {
    setThinking(true);
    abortRef.current = controller;
    activeTaskIdRef.current = taskId;
  }, []);

  const finishTask = useCallback((taskId: string, controller: AbortController) => {
    setThinking(false);
    if (abortRef.current === controller) abortRef.current = null;
    if (activeTaskIdRef.current === taskId) activeTaskIdRef.current = '';
  }, []);

  const stopCurrentRequest = useCallback(() => {
    const taskId = activeTaskIdRef.current;
    if (taskId) api.cancelChatTask(taskId, userId, cancelReason).catch(() => {});
    abortRef.current?.abort();
    abortRef.current = null;
    activeTaskIdRef.current = '';
    setThinking(false);
  }, [cancelReason, userId]);

  return {
    thinking,
    startBusy,
    finishBusy,
    startTask,
    finishTask,
    stopCurrentRequest,
  };
}
