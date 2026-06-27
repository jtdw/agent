import { type PresentationResult } from '@/lib/api';

function statusLabel(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'planning') return '规划中';
  if (normalized === 'awaiting_confirmation') return '待确认';
  if (normalized === 'queued') return '已排队';
  if (normalized === 'running') return '运行中';
  if (normalized === 'waiting_login') return '等待登录';
  if (normalized === 'paused') return '已暂停';
  if (normalized === 'succeeded') return '已完成';
  if (normalized === 'failed') return '失败';
  if (normalized === 'cancelled' || normalized === 'canceled') return '已取消';
  if (normalized === 'blocked') return '已阻塞';
  return '任务';
}

function readableStepLabel(value = '') {
  const normalized = String(value || '').toLowerCase();
  if (!normalized) return '处理步骤';
  if (normalized.includes('download') || normalized.includes('gscloud')) return '提交下载';
  if (normalized.includes('terrain') || normalized.includes('slope') || normalized.includes('aspect')) return '地形分析';
  if (normalized.includes('ndvi') || normalized.includes('algebra')) return '栅格计算';
  if (normalized.includes('clip')) return '裁剪数据';
  if (normalized.includes('reproject')) return '重投影';
  if (normalized.includes('resample')) return '重采样';
  if (normalized.includes('table') && normalized.includes('point')) return '表格转点';
  if (normalized.includes('sample') || normalized.includes('extract')) return '提取特征';
  if (normalized.includes('xgboost') || normalized.includes('model')) return '训练模型';
  if (normalized.includes('map') || normalized.includes('cartography')) return '生成地图';
  return String(value).replace(/_/g, ' ');
}

type TaskDiagnosticsDetailsProps = {
  status: string;
  result: PresentationResult | null;
  diagnostics: Record<string, unknown>;
  showTechnicalDetails: boolean;
};

export function TaskDiagnosticsDetails({ status, result, diagnostics, showTechnicalDetails }: TaskDiagnosticsDetailsProps) {
  return (
    <details className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-900/60">
      <summary className="cursor-pointer font-bold text-slate-600 dark:text-slate-300">诊断详情</summary>
      <div className="mt-2 space-y-1 text-[11px] leading-5 text-slate-500 dark:text-slate-400">
        <div>状态：{statusLabel(status)}</div>
        {result?.executed_steps?.map((step) => <div key={`${step.step_id || step.tool_name}`}>{readableStepLabel(step.tool_name || step.step_id)}?{statusLabel(step.status || '')}</div>)}
        {showTechnicalDetails && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap">{JSON.stringify(diagnostics, null, 2)}</pre>}
      </div>
    </details>
  );
}
