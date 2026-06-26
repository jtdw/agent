import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { api, type ChatMessage } from '@/lib/api';
import { assistantErrorContent } from '../chatMessageContent';

type MergeTaskCardUpdate = (
  current: ChatMessage[],
  matcher: (message: ChatMessage) => boolean,
  update: ChatMessage,
  options?: { consumeAction?: boolean }
) => ChatMessage[];

type UseChatDownloadsArgs = {
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  userId: string;
  sessionId: string;
  mountedRef: MutableRefObject<boolean>;
  messageKey: (message: ChatMessage) => string;
  messageMatchesJob: (message: ChatMessage, jobId: string) => boolean;
  mergeTaskCardUpdate: MergeTaskCardUpdate;
};

export function useChatDownloads({
  messages,
  setMessages,
  userId,
  sessionId,
  mountedRef,
  messageKey,
  messageMatchesJob,
  mergeTaskCardUpdate,
}: UseChatDownloadsArgs) {
  const [gscloudLoginOpen, setGSCloudLoginOpen] = useState(false);
  const [pendingLoginJobId, setPendingLoginJobId] = useState('');
  const [resumeReadyJobIds, setResumeReadyJobIds] = useState<Set<string>>(() => new Set());
  const handledLoginMessageRef = useRef('');
  const announcedDownloadJobsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const message = [...messages].reverse().find((item) => item.meta?.action_required?.type === 'login_required');
    const jobId = String(message?.meta?.action_required?.job_id || '');
    const key = message ? `${messageKey(message)}:${jobId}` : '';
    if (!message || !jobId || handledLoginMessageRef.current === key || resumeReadyJobIds.has(jobId)) return;
    handledLoginMessageRef.current = key;
    setPendingLoginJobId(jobId);
    setGSCloudLoginOpen(true);
  }, [messageKey, messages, resumeReadyJobIds]);

  const openGSCloudLogin = (jobId: string) => {
    setPendingLoginJobId(jobId);
    setGSCloudLoginOpen(true);
  };

  const markGSCloudLoginComplete = (jobId: string) => {
    if (jobId) setResumeReadyJobIds((current) => new Set(current).add(jobId));
    setGSCloudLoginOpen(false);
  };

  const closeGSCloudLogin = () => setGSCloudLoginOpen(false);

  const watchDownloadJob = async (jobId: string) => {
    for (let attempt = 0; attempt < 450; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      if (!mountedRef.current) return;
      try {
        const result = await api.jobs(userId, sessionId);
        const view = result.management_views?.find((item) => item.task_id === jobId);
        const job = (result.jobs || []).find((item) => item.job_id === jobId);
        const status = view?.status || job?.status || '';
        if (!job && !view) continue;
        if ((status === 'completed' || status === 'success' || status === 'succeeded') && !announcedDownloadJobsRef.current.has(jobId)) {
          announcedDownloadJobsRef.current.add(jobId);
          const artifactRefs = view?.artifact_refs || job?.artifacts || [];
          const summary = view?.user_message || '下载完成。结果文件已注册，可以直接下载。';
          setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
            role: 'assistant',
            content: summary,
            meta: {
              artifacts: artifactRefs,
              reason: 'download_success',
              interaction_type: 'tool_task',
              management_view: view,
              presentation_result: {
                schema_version: 'presentation-result/v1',
                status: 'succeeded',
                concise_summary: summary,
                artifact_refs: artifactRefs,
                map_layer_refs: view?.map_layer_refs || [],
                warnings: view?.warnings || [],
                next_action_suggestions: view?.available_actions?.includes('view_artifacts') ? ['查看或下载结果文件'] : [],
              },
              execution_summary: {
                schema_version: 'execution-summary/v1',
                status: 'succeeded',
                summary,
                artifact_count: Array.isArray(artifactRefs) ? artifactRefs.length : 0,
              },
            }
          }));
          return;
        }
        if (status === 'failed' || status === 'canceled' || status === 'cancelled') {
          const failedStatus = status === 'canceled' || status === 'cancelled' ? 'cancelled' : 'failed';
          const summary = view?.user_message || view?.error_title || '任务失败或已取消。';
          setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
            role: 'assistant',
            content: summary,
            meta: {
              reason: 'download_failed',
              interaction_type: 'tool_task',
              management_view: view,
              presentation_result: {
                schema_version: 'presentation-result/v1',
                status: failedStatus,
                concise_summary: view?.display_title || '下载任务',
                artifact_refs: [],
                warnings: view?.warnings || [],
                error_summary: summary,
                next_action_suggestions: view?.available_actions?.includes('retry') ? ['重试任务'] : [],
              },
              execution_summary: {
                schema_version: 'execution-summary/v1',
                status: failedStatus,
                summary,
              },
            }
          }));
          return;
        }
      } catch {
        // Keep polling through transient API failures.
      }
    }
  };

  const resumeDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      const result = await api.resumeDownloadJob(jobId);
      const content = result.auto_started
        ? '已恢复当前下载任务，任务正在运行。完成后会在对话中显示下载文件。'
        : result.reason === 'clarification_required'
          ? '任务仍缺少下载参数，请先补充范围或其他必要参数。'
          : '任务尚未恢复，请检查登录状态。';
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content,
        meta: {
          reason: result.reason || 'download_resume',
          interaction_type: 'tool_task',
          management_view: result.management_view,
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: result.auto_started ? 'running' : 'awaiting_confirmation',
            concise_summary: content,
            artifact_refs: [],
            warnings: [],
            next_action_suggestions: result.auto_started ? [] : ['检查登录状态后继续'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: result.auto_started ? 'running' : 'awaiting_confirmation',
            summary: content,
          },
        }
      }));
      if (result.auto_started) void watchDownloadJob(jobId);
      setResumeReadyJobIds((current) => {
        const next = new Set(current);
        next.delete(jobId);
        return next;
      });
    } catch (cause) {
      setMessages((current) => [...current, { role: 'assistant', content: assistantErrorContent(cause), meta: { reason: 'error' } }]);
    }
  };

  const cancelDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      await api.cancelDownloadJob(jobId, userId, '用户在登录引导中取消任务。', sessionId);
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content: '下载任务已取消。',
        meta: {
          reason: 'download_cancelled',
          interaction_type: 'tool_task',
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: 'cancelled',
            concise_summary: '下载任务已取消。',
            artifact_refs: [],
            warnings: [],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: 'cancelled',
            summary: '下载任务已取消。',
          },
        }
      }));
      setGSCloudLoginOpen(false);
    } catch (cause) {
      setMessages((current) => [...current, { role: 'assistant', content: assistantErrorContent(cause), meta: { reason: 'error' } }]);
    }
  };

  const retryDownload = async (jobId: string) => {
    if (!jobId) return;
    try {
      const result = await api.retryDownloadJob(jobId, userId, sessionId);
      const retryJobId = String(result.management_view?.task_id || result.job?.job_id || '');
      const targetJobId = retryJobId || jobId;
      const status = String(result.management_view?.status || result.job?.status || (result.auto_started ? 'running' : 'queued'));
      const content = result.auto_started
        ? '已创建重试任务并开始后台下载。'
        : result.reason === 'login_required'
          ? '已创建重试任务，但需要先完成数据源登录。'
          : '已创建重试任务，等待后台调度。';
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content,
        meta: {
          reason: 'download_retry',
          interaction_type: 'tool_task',
          management_view: result.management_view,
          action_required: status === 'waiting_login' ? { type: 'login_required', job_id: targetJobId } : undefined,
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: status === 'waiting_login' ? 'waiting_login' : status === 'failed' ? 'failed' : 'running',
            concise_summary: content,
            artifact_refs: [],
            warnings: [],
            next_action_suggestions: status === 'waiting_login' ? ['完成登录后继续下载'] : ['等待任务完成'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status,
            summary: content,
          },
        }
      }));
      if (targetJobId && status !== 'waiting_login') void watchDownloadJob(targetJobId);
    } catch (cause) {
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesJob(message, jobId), {
        role: 'assistant',
        content: assistantErrorContent(cause),
        meta: {
          reason: 'download_retry_failed',
          interaction_type: 'tool_task',
          presentation_result: {
            schema_version: 'presentation-result/v1',
            status: 'failed',
            concise_summary: '重试任务失败。',
            artifact_refs: [],
            warnings: [],
            error_summary: assistantErrorContent(cause),
            next_action_suggestions: ['检查任务状态或稍后重试'],
          },
          execution_summary: {
            schema_version: 'execution-summary/v1',
            status: 'failed',
            summary: '重试任务失败。',
          },
        }
      }));
    }
  };

  return {
    gscloudLoginOpen,
    closeGSCloudLogin,
    pendingLoginJobId,
    resumeReadyJobIds,
    openGSCloudLogin,
    markGSCloudLoginComplete,
    resumeDownload,
    cancelDownload,
    retryDownload,
  };
}
