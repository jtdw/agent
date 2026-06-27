import { Activity, AlertTriangle, Check, LogIn, PauseCircle, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/cn';

type AgentProcessStep = {
  id: string;
  title: string;
  detail: string;
  status?: string;
  toolName?: string;
};

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

function StatusIcon({ status }: { status: string }) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'succeeded') return <Check size={15} />;
  if (normalized === 'failed' || normalized === 'blocked') return <AlertTriangle size={15} />;
  if (normalized === 'awaiting_confirmation') return <ShieldCheck size={15} />;
  if (normalized === 'waiting_login') return <LogIn size={15} />;
  if (normalized === 'cancelled' || normalized === 'canceled' || normalized === 'paused') return <PauseCircle size={15} />;
  return <Activity size={15} />;
}

function userReadableStatus(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (['success', 'completed', 'complete'].includes(normalized)) return 'succeeded';
  return normalized || '';
}

function taskPhaseIndex(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'planning') return 0;
  if (normalized === 'awaiting_confirmation' || normalized === 'queued' || normalized === 'blocked') return 1;
  if (normalized === 'running' || normalized === 'waiting_login' || normalized === 'paused') return 2;
  return 3;
}

function processStepVisualStatus(step: AgentProcessStep, index: number, overallStatus: string, total: number) {
  const normalized = userReadableStatus(step.status || '');
  if (['succeeded', 'failed', 'blocked', 'cancelled', 'canceled'].includes(normalized)) return normalized;
  const phase = taskPhaseIndex(overallStatus);
  if (index < Math.min(phase + 1, total - 1)) return 'succeeded';
  if (index === Math.min(phase + 1, total - 1)) return ['failed', 'blocked'].includes(String(overallStatus).toLowerCase()) ? overallStatus : 'running';
  return normalized || 'queued';
}

export function TaskProcessTimeline({ steps, overallStatus }: { steps: AgentProcessStep[]; overallStatus: string }) {
  return (
    <section className="rounded-[18px] border border-slate-200/75 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-900/38">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-black text-slate-900 dark:text-slate-100">处理过程</div>
          <div className="mt-0.5 text-[11px] font-semibold leading-5 text-slate-500 dark:text-slate-400">
            智能体按顺序完成数据检查、工具调用、成果注册和结果说明。
          </div>
        </div>
        <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-black', statusTone(overallStatus))}>
          <StatusIcon status={overallStatus} />{statusLabel(overallStatus)}
        </span>
      </div>
      <div data-testid="task-timeline" className="grid gap-2 lg:grid-cols-2">
        {steps.map((step, index) => {
          const visualStatus = processStepVisualStatus(step, index, overallStatus, steps.length);
          const completed = visualStatus === 'succeeded';
          const active = ['running', 'planning', 'queued', 'waiting_login', 'awaiting_confirmation', 'paused'].includes(visualStatus);
          return (
            <div key={`${step.id}-${index}`} className={cn(
              'rounded-2xl border px-3 py-2.5 text-xs',
              completed && 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200',
              active && !completed && 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950/25 dark:text-blue-200',
              !completed && !active && 'border-slate-200 bg-white text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300',
            )}>
              <div className="flex items-start gap-2">
                <span className={cn(
                  'mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-black',
                  completed ? 'bg-emerald-600 text-white' : active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500 dark:bg-slate-800',
                )}>{completed ? <Check size={12} /> : index + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 font-black">
                    <span>{step.title}</span>
                    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-black', statusTone(visualStatus))}>{statusLabel(visualStatus)}</span>
                  </div>
                  <div className="mt-1 leading-5 opacity-80">{step.detail}</div>
                  {step.toolName && <div className="mt-1 truncate text-[11px] font-semibold opacity-70">工具：{step.toolName}</div>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
