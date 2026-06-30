import { useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { api, type ChatMessage, type UploadSummary, type WorkspaceMention } from '@/lib/api';
import { normalizeWorkspaceMentions } from './useChatWorkspaceMentions';

type UseChatUploadsArgs = {
  userId: string;
  sessionId: string;
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
  setError: Dispatch<SetStateAction<string>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setWorkspaceMentions: Dispatch<SetStateAction<WorkspaceMention[]>>;
};

type UploadSummarySource = Record<string, unknown> | UploadSummary;

function safeBasename(value: unknown) {
  return String(value || '').replace(/\\/g, '/').split('/').pop()?.trim() || '';
}

export function sanitizeUploadSummaries(items: UploadSummarySource[] = []): UploadSummary[] {
  return items.flatMap((item) => {
    const raw = item as Record<string, unknown>;
    const filename = safeBasename(raw.filename) || safeBasename(raw.original_filename) || safeBasename(raw.name);
    if (!filename) return [];
    const summary: UploadSummary = {
      filename,
      type: String(raw.type || ''),
      dataset_name: String(raw.dataset_name || raw.dataset || ''),
      message: String(raw.message || ''),
    };
    const size = Number(raw.size_bytes);
    if (Number.isFinite(size) && size >= 0) summary.size_bytes = size;
    const rows = Number(raw.row_count);
    if (Number.isFinite(rows) && rows >= 0) summary.row_count = rows;
    return [summary];
  });
}

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
      const uploadSummaries = sanitizeUploadSummaries(r.upload_summaries || []);
      setMessages((current) => [
        ...current,
        {
          role: 'system',
          content: summary || `已上传 ${r.count} 个文件。`,
          meta: { upload_summaries: uploadSummaries }
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
