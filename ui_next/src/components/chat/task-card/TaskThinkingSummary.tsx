import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';
import { type TaskThinkingPresentation } from '../taskCardModel';

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

function statusTone(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'succeeded') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200';
  if (normalized === 'failed') return 'bg-rose-50 text-rose-700 dark:bg-rose-950/35 dark:text-rose-200';
  if (normalized === 'blocked' || normalized === 'awaiting_confirmation' || normalized === 'waiting_login') return 'bg-amber-50 text-amber-700 dark:bg-amber-950/35 dark:text-amber-200';
  if (normalized === 'running' || normalized === 'queued' || normalized === 'planning') return 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200';
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200';
}

function userReadableStatus(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (['success', 'completed', 'complete'].includes(normalized)) return 'succeeded';
  return normalized || '';
}

export function TaskThinkingSummary({ thinking }: { thinking: TaskThinkingPresentation }) {
  return (
    <details
      data-testid="task-thinking-summary"
      open={thinking.defaultExpanded}
      className="task-thinking-summary rounded-[18px] border border-cyan-100 bg-cyan-50/55 p-3 text-xs dark:border-cyan-900/55 dark:bg-cyan-950/18"
    >
      <summary className="cursor-pointer list-none">
        <div data-testid="task-card-public-process" className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm font-black text-slate-900 dark:text-slate-100">公开过程</div>
            <div className="mt-1 leading-5 text-slate-600 dark:text-slate-300">{thinking.summary}</div>
          </div>
          <span className="rounded-full bg-white/80 px-2 py-1 text-[10px] font-black text-cyan-700 ring-1 ring-cyan-100 dark:bg-white/10 dark:text-cyan-200 dark:ring-cyan-900/60">可展开</span>
        </div>
      </summary>
      <div className="mt-3 grid gap-2">
        {thinking.steps.map((step, index) => {
          const visualStatus = userReadableStatus(step.status || '');
          const done = visualStatus === 'succeeded';
          const active = ['running', 'planning', 'queued', 'awaiting_confirmation', 'waiting_login', 'paused'].includes(visualStatus);
          return (
            <div key={`${step.id}-${index}`} className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 rounded-2xl border border-white/75 bg-white/82 px-3 py-2 shadow-sm dark:border-white/10 dark:bg-slate-950/30">
              <span className={cn(
                'mt-0.5 grid h-5 w-5 place-items-center rounded-full text-[10px] font-black',
                done && 'bg-emerald-600 text-white',
                active && !done && 'bg-blue-600 text-white',
                !done && !active && 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-200',
              )}>{done ? <Check size={12} /> : index + 1}</span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 font-black text-slate-800 dark:text-slate-100">
                  <span>{step.title}</span>
                  <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-black', statusTone(step.status))}>{statusLabel(step.status)}</span>
                </div>
                <div className="mt-1 leading-5 text-slate-600 dark:text-slate-300">{step.detail}</div>
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
}
