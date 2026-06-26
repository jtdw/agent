import { Activity, ArrowRight, CheckCircle2, CircleDashed, Clock3, FileText, Layers3, ListChecks, PauseCircle, ShieldQuestion, TriangleAlert, XCircle } from 'lucide-react';
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

function statusSpineClass(status: TaskSummaryStatus) {
  if (status === 'succeeded') return 'bg-emerald-400';
  if (status === 'failed' || status === 'cancelled') return 'bg-rose-400';
  if (status === 'awaiting_confirmation' || status === 'waiting_login' || status === 'paused') return 'bg-amber-400';
  if (status === 'running' || status === 'planning' || status === 'queued') return 'bg-cyan-500';
  return 'bg-slate-300 dark:bg-slate-700';
}

function realtimeLabel(realtimeState: TaskSummaryRailProps['realtimeState']) {
  if (realtimeState === 'live') return '实时同步';
  if (realtimeState === 'connecting') return '连接中';
  return '轮询同步';
}

export function TaskSummaryRail({ taskSummaryItems, realtimeState, messageCount }: TaskSummaryRailProps) {
  const activeCount = taskSummaryItems.filter((item) => ['planning', 'queued', 'running', 'awaiting_confirmation', 'waiting_login', 'paused'].includes(item.status)).length;
  return (
    <aside
      data-testid="chat-task-summary-rail"
      className="chat-task-summary-rail hidden min-h-0 border-l border-slate-200/80 bg-[linear-gradient(180deg,rgba(248,250,252,.94),rgba(236,253,245,.42)_52%,rgba(239,246,255,.56))] p-3 dark:border-slate-800 dark:bg-[linear-gradient(180deg,rgba(2,6,23,.78),rgba(6,78,59,.18)_52%,rgba(15,23,42,.62))] lg:col-start-3 lg:row-span-3 lg:row-start-1 lg:flex lg:flex-col"
    >
      <div data-testid="chat-task-workbench-header" className="rounded-2xl border border-white/75 bg-white/88 p-3 shadow-[0_14px_34px_rgba(15,23,42,.06)] dark:border-slate-800 dark:bg-slate-900/68">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-black text-slate-950 dark:text-slate-50">
              <ListChecks size={16} className="text-emerald-600 dark:text-emerald-300" />
              GIS 任务工作台
            </div>
            <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">Live process rail</div>
          </div>
          <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-black text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-950/28 dark:text-emerald-200 dark:ring-emerald-900/70">{taskSummaryItems.length} 项</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-slate-100 bg-slate-50 px-2.5 py-2 dark:border-slate-800 dark:bg-slate-950/44">
            <div className="text-[10px] font-bold text-slate-400">对话消息</div>
            <div className="mt-0.5 text-sm font-black text-slate-800 dark:text-slate-100">{messageCount}</div>
          </div>
          <div className="rounded-xl border border-amber-100 bg-amber-50/70 px-2.5 py-2 dark:border-amber-950/60 dark:bg-amber-950/18">
            <div className="text-[10px] font-bold text-amber-600 dark:text-amber-300">实时任务</div>
            <div className="mt-0.5 text-sm font-black text-slate-800 dark:text-slate-100">{activeCount}</div>
          </div>
        </div>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-cyan-50 px-2 py-1 text-[10px] font-black text-cyan-700 dark:bg-cyan-950/28 dark:text-cyan-200">
          <Clock3 size={12} />{realtimeLabel(realtimeState)}
        </div>
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {taskSummaryItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white/58 p-4 text-xs leading-5 text-slate-400 dark:border-slate-800 dark:bg-slate-900/35">
            当前对话还没有 GIS 工具任务。任务开始后，这里会显示执行状态、公开过程和结果产物。
          </div>
        ) : (
          taskSummaryItems.map((item) => (
            <article
              key={item.id}
              data-testid="chat-task-summary-item"
              className="relative overflow-hidden rounded-2xl border border-white/75 bg-white/88 p-3 pl-4 shadow-[0_12px_28px_rgba(15,23,42,.055)] dark:border-slate-800 dark:bg-slate-900/62"
            >
              <div className={cn('task-rail-spine absolute bottom-3 left-2 top-3 w-1 rounded-full', statusSpineClass(item.status))} />
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

              <div data-testid="chat-task-process-lane" className="mt-3 rounded-xl border border-slate-100 bg-slate-50/88 px-2.5 py-2 dark:border-slate-800 dark:bg-slate-950/42">
                <div className="mb-1 flex items-center justify-between gap-2 text-[10px] font-black text-slate-400 dark:text-slate-500">
                  <span>公开过程</span>
                  <span>{item.syncState || realtimeLabel(realtimeState)}</span>
                </div>
                {(item.progress !== null || item.currentStep) ? (
                  <>
                    <div className="flex items-center justify-between gap-2 text-[10px] font-bold text-slate-500 dark:text-slate-400">
                      <span className="truncate">{item.currentStep || '等待后端同步步骤'}</span>
                      <span>{item.progress !== null ? `${item.progress}%` : '真实进度待同步'}</span>
                    </div>
                    {item.progress !== null && (
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                        <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-cyan-500 to-blue-500" style={{ width: `${item.progress}%` }} />
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-[10px] font-bold leading-4 text-slate-500 dark:text-slate-400">等待后端同步公开步骤</div>
                )}
              </div>

              {(item.artifactCount > 0 || item.mapLayerCount > 0 || item.primaryResultLabel) && (
                <div data-testid="chat-task-result-strip" className="mt-3 rounded-xl border border-slate-100 bg-white/70 p-2 dark:border-slate-800 dark:bg-slate-950/30">
                  <div className="mb-1 text-[10px] font-black text-slate-400 dark:text-slate-500">结果产物</div>
                  <div data-testid="chat-task-summary-artifacts" className="flex flex-wrap items-center gap-1.5">
                    {item.artifactCount > 0 && (
                      <span className="inline-flex min-w-0 items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[10px] font-black text-slate-600 dark:border-slate-800 dark:bg-slate-950/48 dark:text-slate-300">
                        <FileText size={11} />
                        {item.artifactCount} 成果
                      </span>
                    )}
                    {item.mapLayerCount > 0 && (
                      <span className="inline-flex min-w-0 items-center gap-1 rounded-full border border-cyan-100 bg-cyan-50 px-2 py-1 text-[10px] font-black text-cyan-700 dark:border-cyan-950/70 dark:bg-cyan-950/24 dark:text-cyan-200">
                        <Layers3 size={11} />
                        {item.mapLayerCount} 图层
                      </span>
                    )}
                    {item.primaryResultLabel && (
                      <span title={item.primaryResultLabel} className="min-w-0 max-w-full truncate rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-slate-800/70 dark:text-slate-300">
                        {item.primaryResultLabel}
                      </span>
                    )}
                  </div>
                </div>
              )}
              {item.nextActions.length > 0 && (
                <div data-testid="chat-task-summary-next-actions" className="mt-2 space-y-1 border-t border-slate-100 pt-2 dark:border-slate-800/80">
                  {item.nextActions.map((action) => (
                    <div key={action} className="flex min-w-0 items-start gap-1.5 text-[10px] font-bold leading-4 text-slate-500 dark:text-slate-400">
                      <ArrowRight size={11} className="mt-0.5 shrink-0 text-blue-500 dark:text-cyan-300" />
                      <span className="line-clamp-2">{action}</span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          ))
        )}
      </div>
    </aside>
  );
}
