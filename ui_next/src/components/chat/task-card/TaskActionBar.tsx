import { Check, LogIn, Play, RefreshCcw, ShieldCheck, XCircle } from 'lucide-react';
import { type ChatMessage } from '@/lib/api';

function canCancelTask(status: string, actionType = '', availableActions: unknown[] = []) {
  const normalized = String(status || '').toLowerCase();
  if (actionType === 'login_required') return true;
  if (availableActions.map(String).includes('cancel')) return true;
  return ['planning', 'awaiting_confirmation', 'queued', 'running', 'waiting_login', 'paused'].includes(normalized);
}

function canRetryTask(status: string, availableActions: unknown[] = []) {
  const normalized = String(status || '').toLowerCase();
  if (availableActions.map(String).includes('retry')) return true;
  return ['failed', 'blocked', 'cancelled', 'canceled'].includes(normalized);
}

type TaskActionBarProps = {
  action?: NonNullable<ChatMessage['meta']>['action_required'];
  status: string;
  actionType: string;
  availableActions: unknown[];
  jobId: string;
  confirmationPrompt: string;
  confirmedActionId: string;
  resumeReady?: boolean;
  onLogin?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  onRetry?: (jobId: string) => void;
  onClarification?: (value: string, label: string) => void;
  onConfirmAction?: (prompt: string, confirmedActionId: string) => void;
};

export function TaskActionBar({
  action,
  status,
  actionType,
  availableActions,
  jobId,
  confirmationPrompt,
  confirmedActionId,
  resumeReady,
  onLogin,
  onResume,
  onCancel,
  onRetry,
  onClarification,
  onConfirmAction,
}: TaskActionBarProps) {
  return (
    <div className="flex flex-wrap gap-2 rounded-[18px] border border-slate-200/70 bg-white/70 p-2 dark:border-slate-800 dark:bg-slate-950/28">
      {action?.type === 'confirmation_required' && confirmationPrompt && confirmedActionId && (
        <button type="button" onClick={() => onConfirmAction?.(confirmationPrompt, confirmedActionId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700">
          <ShieldCheck size={14} />确认执行
        </button>
      )}
      {action?.type === 'login_required' && !resumeReady && <button type="button" onClick={() => onLogin?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><LogIn size={14} />登录</button>}
      {action?.type === 'login_required' && resumeReady && <button type="button" onClick={() => onResume?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"><Play size={14} />登录后继续</button>}
      {jobId && canCancelTask(status, actionType, availableActions) && <button type="button" onClick={() => onCancel?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-coral"><XCircle size={14} />取消</button>}
      {jobId && canRetryTask(status, availableActions) && <button type="button" onClick={() => onRetry?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><RefreshCcw size={14} />重试</button>}
      {action?.type === 'clarification_required' && Array.isArray(action.options) && action.options.map((option) => (
        <button key={option.value} type="button" onClick={() => onClarification?.(option.value, option.label)} className="glass-button px-3 py-2 text-xs font-black">{option.label}</button>
      ))}
      {!action?.type && status === 'succeeded' && <span className="inline-flex items-center gap-1.5 px-2 py-2 text-xs font-bold text-slate-500 dark:text-slate-400"><Check size={14} />任务已完成</span>}
    </div>
  );
}
