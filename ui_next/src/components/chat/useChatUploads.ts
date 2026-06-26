import { useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { api, type ChatMessage, type WorkspaceMention } from '@/lib/api';
import { normalizeWorkspaceMentions } from './useChatWorkspaceMentions';

type UseChatUploadsArgs = {
  userId: string;
  sessionId: string;
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
  setError: Dispatch<SetStateAction<string>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setWorkspaceMentions: Dispatch<SetStateAction<WorkspaceMention[]>>;
};

export function useChatUploads({
  userId,
  sessionId,
  fileInputRef,
  setError,
  setMessages,
  setWorkspaceMentions,
}: UseChatUploadsArgs) {
  const [uploading, setUploading] = useState(false);

  const uploadFiles = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    if (!userId) {
      setError('请先登录账号，再上传数据。');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }
    setUploading(true);
    setError('');
    try {
      const r = await api.uploadFiles(files, userId, sessionId);
      setWorkspaceMentions(normalizeWorkspaceMentions(r.dashboard?.datasets || []));
      const summary = r.outcome_markdown || '';
      setMessages((current) => [
        ...current,
        {
          role: 'system',
          content: summary || `已上传 ${r.count} 个文件。`,
          meta: { upload_summaries: r.upload_summaries || [] }
        }
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return { uploading, uploadFiles };
}
