import { Activity, CheckCircle2, CircleDashed, Clock3, ListChecks, PauseCircle, ShieldQuestion, TriangleAlert, XCircle } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { ChatTaskSummaryItem, TaskSummaryStatus } from './chatWorkspaceModel';

type TaskSummaryRailProps = {
  taskSummaryItems: ChatTaskSummaryItem[];
  realtimeState: 'connecting' | 'live' | 'polling';
  messageCount: number;
};

function statusIcon(status: TaskSummaryStatus) {
  if (status === 'succeeded') return <CheckCircle2 size={15} />;
  if (status === 'failed') return <TriangleAlert size={15} />;
  if (status === 'cancelled') return <XCircle size={15} />;
  if (status === 'paused') return <PauseCircle size={15} />;
  if (status === 'awaiting_confirmation' || status === 'waiting_login') return <ShieldQuestion size={15} />;
  if (status === 'running') return <Activity size={15} />;
  return <CircleDashed size={15} />;
}

function statusLabel(status: TaskSummaryStatus) {
  if (status === 'planning') return '规划';
  if (status === 'queued') return '排队';
  if (status === 'running') return '执行中';
  if (status === 'awaiting_confirmation') return '待确认';
  if (status === 'waiting_login') return '待登录';
  if (status === 'paused') return '暂停';
  if (status === 'succeeded') return '完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return '待同步';
}

function statusClass(status: TaskSummaryStatus) {
  if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/24 dark:text-emerald-200';
  if (status === 'failed' || status === 'cancelled') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/24 dark:text-rose-200';
  if (status === 'awaiting_confirmation' || status === 'waiting_login' || status === 'paused') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/24 dark:text-amber-200';
  if (status === 'running' || status === 'planning' || status === 'queued') return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/24 dark:text-blue-200';
  return 'border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/45 dark:text-slate-300';
}

export function TaskSummaryRail({ taskSummaryItems, realtimeState, messageCount }: TaskSummaryRailProps) {
  const activeCount = taskSummaryItems.filter((item) => ['planning', 'queued', 'running', 'awaiting_confirmation', 'waiting_login', 'paused'].includes(item.status)).length;
  return (
    <aside
      data-testid="chat-task-summary-rail"
      className="chat-task-summary-rail hidden min-h-0 border-l border-slate-200/80 bg-slate-50/72 p-3 dark:border-slate-800 dark:bg-slate-950/34 lg:col-start-3 lg:row-span-3 lg:row-start-1 lg:flex lg:flex-col"
    >
      <div className="rounded-2xl border border-white/75 bg-white/78 p-3 shadow-[0_14px_34px_rgba(15,23,42,.06)] dark:border-slate-800 dark:bg-slate-900/58">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-black text-slate-950 dark:text-slate-50">
            <ListChecks size={16} className="text-blue-600 dark:text-cyan-300" />
            任务摘要
          </div>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-500 dark:bg-slate-800 dark:text-slate-300">{taskSummaryItems.length}</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-slate-50 px-2.5 py-2 dark:bg-slate-950/44">
            <div className="text-[10px] font-bold text-slate-400">消息</div>
            <div className="mt-0.5 text-sm font-black text-slate-800 dark:text-slate-100">{messageCount}</div>
          </div>
          <div className="rounded-xl bg-slate-50 px-2.5 py-2 dark:bg-slate-950/44">
            <div className="text-[10px] font-bold text-slate-400">活跃</div>
            <div className="mt-0.5 text-sm font-black text-slate-800 dark:text-slate-100">{activeCount}</div>
          </div>
        </div>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-cyan-50 px-2 py-1 text-[10px] font-black text-cyan-700 dark:bg-cyan-950/28 dark:text-cyan-200">
          <Clock3 size={12} />{realtimeState === 'live' ? '实时同步' : realtimeState === 'connecting' ? '连接中' : '轮询同步'}
        </div>
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {taskSummaryItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white/58 p-4 text-xs leading-5 text-slate-400 dark:border-slate-800 dark:bg-slate-900/35">
            当前对话还没有工具任务。任务开始后，这里会显示执行状态、公开过程和下一步动作。
          </div>
        ) : (
          taskSummaryItems.map((item) => (
            <article
              key={item.id}
              data-testid="chat-task-summary-item"
              className="rounded-2xl border border-white/75 bg-white/84 p-3 shadow-[0_12px_28px_rgba(15,23,42,.055)] dark:border-slate-800 dark:bg-slate-900/58"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-xs font-black text-slate-950 dark:text-slate-50">{item.title}</div>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-slate-500 dark:text-slate-400">{item.summary}</p>
                </div>
                <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-black', statusClass(item.status))}>
                  {statusIcon(item.status)}
                  {statusLabel(item.status)}
                </span>
              </div>
              {(item.progress !== null || item.currentStep) && (
                <div className="mt-3 rounded-xl bg-slate-50 px-2.5 py-2 dark:bg-slate-950/42">
                  <div className="flex items-center justify-between gap-2 text-[10px] font-bold text-slate-500 dark:text-slate-400">
                    <span className="truncate">{item.currentStep || '等待后端同步步骤'}</span>
                    <span>{item.progress !== null ? `${item.progress}%` : '真实进度待同步'}</span>
                  </div>
                  {item.progress !== null && (
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div className="h-full rounded-full bg-gradient-to-r from-blue-600 to-cyan-500" style={{ width: `${item.progress}%` }} />
                    </div>
                  )}
                </div>
              )}
            </article>
          ))
        )}
      </div>
    </aside>
  );
}
