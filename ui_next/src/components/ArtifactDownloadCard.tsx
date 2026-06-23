import {
  AlertTriangle,
  Download,
  Eye,
  FileArchive,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
  Loader2,
  Trash2
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, type ChatArtifact } from '@/lib/api';
import { cn } from '@/lib/cn';

function artifactIcon(kind = '', filename = '') {
  const text = `${kind} ${filename}`.toLowerCase();
  if (/\.(png|jpg|jpeg|webp)$/.test(text)) return FileImage;
  if (/\.(csv|xlsx|xls)$/.test(text)) return FileSpreadsheet;
  if (/\.(zip)$/.test(text) || text.includes('shp_zip')) return FileArchive;
  if (/\.(json|geojson)$/.test(text)) return FileJson;
  return FileText;
}

function isImageArtifact(artifact: ChatArtifact, filename = '') {
  const text = `${artifact.mime_type || ''} ${artifact.kind || ''} ${artifact.type || ''} ${filename}`.toLowerCase();
  return text.includes('image/') || /\b(image|plot|visual|map)\b/.test(text) || /\.(png|jpg|jpeg|webp|svg)(\?|$)/.test(text);
}

function previewRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function previewRows(value: unknown): Array<Record<string, unknown>> {
  const preview = previewRecord(value);
  return Array.isArray(preview.rows) ? preview.rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object') : [];
}

function previewColumns(value: unknown, rows: Array<Record<string, unknown>>): string[] {
  const preview = previewRecord(value);
  const columns = Array.isArray(preview.columns) ? preview.columns.map(String).filter(Boolean) : [];
  if (columns.length) return columns.slice(0, 6);
  return Object.keys(rows[0] || {}).slice(0, 6);
}

function isMarkdownArtifact(artifact: ChatArtifact, filename = '') {
  const text = `${artifact.mime_type || ''} ${artifact.kind || ''} ${artifact.type || ''} ${artifact.artifact_type || ''} ${filename}`.toLowerCase();
  return text.includes('markdown') || text.includes('report') || /\.(md|txt)$/.test(filename.toLowerCase());
}

function isJsonArtifact(artifact: ChatArtifact, filename = '') {
  const text = `${artifact.mime_type || ''} ${artifact.kind || ''} ${artifact.type || ''} ${artifact.artifact_type || ''} ${filename}`.toLowerCase();
  return text.includes('json') || /\.json$/.test(filename.toLowerCase());
}

export function formatFileSize(bytes?: number, sizeKb?: number) {
  const value = typeof bytes === 'number' && bytes > 0 ? bytes : Math.round((sizeKb || 0) * 1024);
  if (!value) return '未知大小';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatTime(value?: string) {
  if (!value) return '未知时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

export function ArtifactDownloadCard({
  artifact,
  userId,
  sessionId,
  onDeleted,
  onShowOnMap
}: {
  artifact: ChatArtifact;
  userId?: string;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
  onShowOnMap?: (artifact: ChatArtifact) => void;
}) {
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [mapping, setMapping] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [resolvedArtifact, setResolvedArtifact] = useState<ChatArtifact | null>(null);
  const [resolving, setResolving] = useState(false);
  const resolved = resolvedArtifact ? { ...artifact, ...resolvedArtifact } : artifact;
  const filename = resolved.filename || resolved.name || resolved.title || 'artifact';
  const Icon = artifactIcon(resolved.kind || resolved.type, filename);
  const source = resolved.source?.tool_name || resolved.source?.workflow_id || 'GIS 处理结果';
  const missing = resolved.status === 'missing';
  const mapReady = Boolean(resolved.map_ready || resolved.meta?.map_ready || resolved.meta?.map_layer_id || resolved.meta?.dataset_name);
  const resolvedDownloadUrl = resolved.download_url || (!resolved.artifact_id ? artifact.download_url : '');
  const canDownload = Boolean(resolved.artifact_id) && !deleted && !missing;
  const imagePreviewUrl = !missing && isImageArtifact(resolved, filename) && resolvedDownloadUrl ? resolvedDownloadUrl : '';
  const rows = previewRows(resolved.preview);
  const columns = previewColumns(resolved.preview, rows);
  const markdownPreview = typeof resolved.preview === 'string' && isMarkdownArtifact(resolved, filename) ? resolved.preview : '';
  const jsonPreview = resolved.preview && !rows.length && isJsonArtifact(resolved, filename) ? JSON.stringify(resolved.preview, null, 2) : '';

  useEffect(() => {
    if (!artifact.artifact_id || deleted) return;
    let cancelled = false;
    setResolving(true);
    api.artifactMetadata(artifact.artifact_id, userId, sessionId)
      .then((metadata) => {
        if (!cancelled) setResolvedArtifact(metadata);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : '无法解析结果文件');
      })
      .finally(() => {
        if (!cancelled) setResolving(false);
      });
    return () => {
      cancelled = true;
    };
  }, [artifact.artifact_id, userId, sessionId, deleted]);

  const download = async () => {
    if (downloading || deleted || missing) return;
    if (!resolved.artifact_id) {
      setError('文件已清理、无访问权限或下载链接已失效。');
      return;
    }
    setDownloading(true);
    setError('');
    try {
      await api.downloadArtifactById(resolved.artifact_id, filename, userId, sessionId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '文件已清理、无访问权限或下载链接已失效。');
    } finally {
      setDownloading(false);
    }
  };

  const remove = async () => {
    if (!artifact.artifact_id || deleting || deleted) return;
    if (!window.confirm(`删除结果文件 ${filename}？此操作会删除服务器中的结果文件。`)) return;
    setDeleting(true);
    setError('');
    try {
      await api.deleteArtifact(artifact.artifact_id, userId, true, sessionId);
      setDeleted(true);
      onDeleted?.(artifact.artifact_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const showOnMap = async () => {
    if (deleted || mapping || missing) return;
    if (onShowOnMap) {
      onShowOnMap(artifact);
      return;
    }
    setMapping(true);
    setError('');
    try {
      const result = await api.refreshMapLayer({ user_id: userId, session_id: sessionId, artifact_id: resolved.artifact_id });
      window.dispatchEvent(new CustomEvent('gis:show-artifact-on-map', { detail: { artifact: resolved, result } }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法显示到地图');
    } finally {
      setMapping(false);
    }
  };

  return (
    <div data-testid="artifact-download-card" className={cn('artifact-download-card', deleted && 'opacity-65')}>
      <div className="artifact-file-icon"><Icon size={18} strokeWidth={1.8} /></div>
      <div className="min-w-0 flex-1 overflow-hidden">
        <div className="flex min-w-0 items-center gap-2">
          <span className="artifact-file-name text-sm font-bold text-slate-800 dark:text-slate-100">{filename}</span>
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-300">{artifact.mime_type || artifact.kind || artifact.type || 'file'}</span>
        </div>
        <div className="artifact-meta-line mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">
          <span>{formatFileSize(resolved.size_bytes, resolved.size_kb)}</span>
          <span>{formatTime(resolved.created_at || resolved.updated_at)}</span>
          <span className="min-w-0 max-w-full truncate">来源：{source}</span>
          {resolving && <span>正在校验下载入口</span>}
          {deleted && <span className="font-bold text-rose-500">已删除</span>}
          {missing && <span className="font-bold text-amber-600">文件失效</span>}
        </div>
        {imagePreviewUrl && !deleted && (
          <a data-testid="artifact-image-preview" href={imagePreviewUrl} target="_blank" rel="noreferrer" className="artifact-preview-image mt-3 block overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
            <img src={imagePreviewUrl} alt={filename} loading="lazy" className="max-h-52 w-full object-contain" />
          </a>
        )}
        {rows.length > 0 && !deleted && (
          <div data-testid="artifact-table-preview" className="mt-3 max-h-56 overflow-auto rounded-lg border border-slate-200 bg-white text-[11px] dark:border-slate-800 dark:bg-slate-950">
            <table className="min-w-full">
              <thead className="sticky top-0 bg-slate-50 text-slate-500 dark:bg-slate-900 dark:text-slate-300">
                <tr>{columns.map((column) => <th key={column} className="px-2 py-1 text-left font-bold">{column}</th>)}</tr>
              </thead>
              <tbody>
                {rows.slice(0, 20).map((row) => (
                  <tr key={columns.map((column) => String(row[column] ?? '')).join('|') || JSON.stringify(row)} className="border-t border-slate-100 dark:border-slate-800">
                    {columns.map((column) => <td key={column} className="max-w-40 truncate px-2 py-1">{String(row[column] ?? '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {markdownPreview && !deleted && (
          <pre data-testid="artifact-markdown-preview" className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
            {markdownPreview.slice(0, 1600)}
          </pre>
        )}
        {jsonPreview && !deleted && (
          <pre data-testid="artifact-json-preview" className="mt-3 max-h-44 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
            {jsonPreview.slice(0, 1600)}
          </pre>
        )}
        {missing && !deleted && <div className="mt-2 inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-200"><AlertTriangle size={12} /> 文件失效，无法预览或下载</div>}
        {error && <div className="mt-2 inline-flex items-center gap-1 rounded-lg bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-600 dark:bg-rose-950/40 dark:text-rose-300"><AlertTriangle size={12} /> {error}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {(mapReady || onShowOnMap) && (
          <button type="button" onClick={showOnMap} className="artifact-card-action" title="显示到地图" aria-label="显示到地图" disabled={deleted || mapping || missing}>
            {mapping ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />}
          </button>
        )}
        <button data-testid="artifact-delete" type="button" onClick={remove} disabled={deleting || deleted || !artifact.artifact_id} className="artifact-card-action" title="删除" aria-label="删除结果文件">
          {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
        </button>
        <button data-testid="artifact-download" type="button" onClick={download} disabled={downloading || resolving || !canDownload} className={cn('artifact-card-action is-primary', downloading && 'opacity-60')} title={canDownload ? '下载' : '文件已清理、无访问权限或下载链接已失效'} aria-label="下载">
          {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
        </button>
      </div>
    </div>
  );
}
