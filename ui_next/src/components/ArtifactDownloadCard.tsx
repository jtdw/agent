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
import { useState } from 'react';
import { api, type ChatArtifact } from '@/lib/api';
import { cn } from '@/lib/cn';

const LARGE_DOWNLOAD_THRESHOLD_BYTES = 25 * 1024 * 1024;

function artifactIcon(kind = '', filename = '') {
  const text = `${kind} ${filename}`.toLowerCase();
  if (/\.(png|jpg|jpeg|webp)$/.test(text)) return FileImage;
  if (/\.(csv|xlsx|xls)$/.test(text)) return FileSpreadsheet;
  if (/\.(zip)$/.test(text) || text.includes('shp_zip')) return FileArchive;
  if (/\.(json|geojson)$/.test(text)) return FileJson;
  return FileText;
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
  const filename = artifact.filename || artifact.name || artifact.title || 'artifact';
  const Icon = artifactIcon(artifact.kind || artifact.type, filename);
  const source = artifact.source?.tool_name || artifact.source?.workflow_id || 'GIS 处理结果';
  const mapReady = Boolean(artifact.meta?.map_ready || artifact.meta?.map_layer_id || artifact.meta?.dataset_name);

  const download = async () => {
    if (!artifact.download_url || downloading || deleted) return;
    setDownloading(true);
    setError('');
    try {
      if ((artifact.size_bytes || 0) >= LARGE_DOWNLOAD_THRESHOLD_BYTES) {
        api.downloadNative(artifact.download_url, filename);
      } else {
        await api.downloadAuthenticated(artifact.download_url, filename);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '下载失败');
    } finally {
      setDownloading(false);
    }
  };

  const remove = async () => {
    if (!artifact.artifact_id || deleting || deleted) return;
    const confirmed = window.confirm(`删除结果文件 ${filename}？此操作会删除服务器中的结果文件。`);
    if (!confirmed) return;
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
    if (deleted || mapping) return;
    if (onShowOnMap) {
      onShowOnMap(artifact);
      return;
    }
    setMapping(true);
    setError('');
    try {
      const result = await api.refreshMapLayer({ user_id: userId, session_id: sessionId, artifact_id: artifact.artifact_id });
      window.dispatchEvent(new CustomEvent('gis:show-artifact-on-map', { detail: { artifact, result } }));
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
          <span>{formatFileSize(artifact.size_bytes, artifact.size_kb)}</span>
          <span>{formatTime(artifact.created_at || artifact.updated_at)}</span>
          <span className="min-w-0 max-w-full truncate">来源：{source}</span>
          {deleted && <span className="font-bold text-rose-500">已删除</span>}
        </div>
        {error && <div className="mt-2 inline-flex items-center gap-1 rounded-lg bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-600 dark:bg-rose-950/40 dark:text-rose-300"><AlertTriangle size={12} /> {error}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {(mapReady || onShowOnMap) && (
          <button type="button" onClick={showOnMap} className="artifact-card-action" title="显示到地图" aria-label="显示到地图" disabled={deleted || mapping}>
            {mapping ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />}
          </button>
        )}
        {artifact.preview_available && (
          <button type="button" className="artifact-card-action" title="预览" aria-label="预览" disabled={deleted}>
            <Eye size={15} />
          </button>
        )}
        <button data-testid="artifact-delete" type="button" onClick={remove} disabled={deleting || deleted || !artifact.artifact_id} className="artifact-card-action" title="删除" aria-label="删除结果文件">
          {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
        </button>
        <button data-testid="artifact-download" type="button" onClick={download} disabled={downloading || deleted || !artifact.download_url} className={cn('artifact-card-action is-primary', downloading && 'opacity-60')} title="下载" aria-label="下载">
          {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
        </button>
      </div>
    </div>
  );
}
