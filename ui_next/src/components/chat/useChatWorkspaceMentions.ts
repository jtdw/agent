import { useEffect, useState } from 'react';
import { api, type WorkspaceMention } from '@/lib/api';

type WorkspaceMentionSource = Record<string, unknown> | WorkspaceMention;

type UseChatWorkspaceMentionsArgs = {
  mentionDatasets: WorkspaceMentionSource[];
  userId: string;
  sessionId: string;
};

export function normalizeWorkspaceMentions(items: WorkspaceMentionSource[] = []): WorkspaceMention[] {
  return items.flatMap((item) => {
    const raw = item as Record<string, unknown>;
    const name = String(raw.name || '').trim();
    if (!name) return [];
    const meta = raw.meta && typeof raw.meta === 'object' ? raw.meta as Record<string, unknown> : {};
    const columns = Array.isArray(meta.columns) ? meta.columns : [];
    const filename = String(raw.filename || raw.label || name);
    return [{
      id: String(raw.id || name),
      name,
      mention: String(raw.mention || `@{${name}}`),
      type: String(raw.type || raw.data_type || 'file'),
      filename,
      row_count: Number.isFinite(Number(raw.row_count ?? meta.rows)) ? Number(raw.row_count ?? meta.rows) : null,
      column_count: Number.isFinite(Number(raw.column_count)) ? Number(raw.column_count) : columns.length || null,
      crs: String(raw.crs || meta.crs || '')
    }];
  });
}

export function useChatWorkspaceMentions({ mentionDatasets, userId, sessionId }: UseChatWorkspaceMentionsArgs) {
  const [workspaceMentions, setWorkspaceMentions] = useState<WorkspaceMention[]>(() => normalizeWorkspaceMentions(mentionDatasets));

  useEffect(() => {
    setWorkspaceMentions(normalizeWorkspaceMentions(mentionDatasets));
  }, [mentionDatasets]);

  useEffect(() => {
    if (!userId) {
      setWorkspaceMentions([]);
      return;
    }
    api.workspaceMentions(userId, sessionId)
      .then((result) => setWorkspaceMentions(normalizeWorkspaceMentions(result.items || [])))
      .catch(() => {});
  }, [userId, sessionId]);

  return { workspaceMentions, setWorkspaceMentions };
}
