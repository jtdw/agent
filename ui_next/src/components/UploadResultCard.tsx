import { CheckCircle2, FileJson, FileSpreadsheet, FileText, Map } from 'lucide-react';
import type { UploadSummary } from '@/lib/api';
import { formatFileSize } from './ArtifactDownloadCard';

function uploadIcon(type = '', filename = '') {
  const text = `${type} ${filename}`.toLowerCase();
  if (text.includes('geojson') || text.includes('shp') || text.includes('vector')) return Map;
  if (text.includes('csv') || text.includes('xlsx') || text.includes('table')) return FileSpreadsheet;
  if (text.includes('json')) return FileJson;
  return FileText;
}

export function UploadResultCard({ summaries }: { summaries: UploadSummary[] }) {
  if (!summaries.length) return null;
  return (
    <div data-testid="upload-result-card" className="upload-result-card">
      <div className="flex items-center gap-2 text-sm font-black text-slate-800 dark:text-slate-100">
        <CheckCircle2 size={16} className="text-emerald-500" />
        已上传 {summaries.length} 个文件
      </div>
      <div className="mt-3 grid gap-2">
        {summaries.map((item) => {
          const Icon = uploadIcon(item.type, item.filename);
          return (
            <div key={`${item.filename}-${item.dataset_name || item.type}`} className="upload-result-row">
              <div className="upload-result-icon"><Icon size={15} /></div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-bold text-slate-800 dark:text-slate-100">{item.filename}</div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">
                  <span>{item.type || 'file'}</span>
                  <span>{formatFileSize(item.size_bytes)}</span>
                  {typeof item.row_count === 'number' && <span>{item.row_count} 行</span>}
                  {item.dataset_name && <span>数据集：{item.dataset_name}</span>}
                </div>
              </div>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-black text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-300">
                已载入
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 text-xs font-semibold text-slate-500 dark:text-slate-400">
        可以继续检查字段、坐标、时间和缺失值，或直接发起建模、制图任务。
      </div>
    </div>
  );
}
