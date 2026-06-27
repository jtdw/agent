import { Activity, AlertTriangle, Check, Gauge, LogIn, PauseCircle, RefreshCcw, ShieldCheck } from 'lucide-react';
import { type ChatMessage, type PresentationResult } from '@/lib/api';
import { cn } from '@/lib/cn';
import { buildTaskCardPresentation } from '../taskCardModel';
import { TaskActionBar } from './TaskActionBar';
import { TaskDiagnosticsDetails } from './TaskDiagnosticsDetails';
import { TaskProcessTimeline } from './TaskProcessTimeline';
import { ResultGroups } from './TaskResultGroups';
import { TaskThinkingSummary } from './TaskThinkingSummary';

function stableTextKey(prefix: string, value: unknown) {
  const text = String(value || '');
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  return `${prefix}-${Math.abs(hash).toString(36)}-${text.length}`;
}
function technicalDetailsEnabled() {
  if (import.meta.env.VITE_SHOW_TECHNICAL_DETAILS === 'true') return true;
  try {
    return localStorage.getItem('gis-agent-developer-mode') === '1';
  } catch {
    return false;
  }
}

function metaRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

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
  if (normalized === 'blocked') return '已阻断';
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

function statusAccent(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'succeeded') return 'from-emerald-500 to-teal-500';
  if (normalized === 'failed') return 'from-rose-500 to-red-500';
  if (normalized === 'blocked' || normalized === 'awaiting_confirmation' || normalized === 'waiting_login') return 'from-amber-500 to-orange-500';
  if (normalized === 'cancelled' || normalized === 'canceled' || normalized === 'paused') return 'from-slate-500 to-slate-400';
  return 'from-blue-600 to-cyan-500';
}

function statusSpine(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'succeeded') return 'bg-emerald-400';
  if (normalized === 'failed' || normalized === 'blocked') return 'bg-rose-400';
  if (normalized === 'awaiting_confirmation' || normalized === 'waiting_login') return 'bg-amber-400';
  if (normalized === 'cancelled' || normalized === 'canceled' || normalized === 'paused') return 'bg-slate-400';
  return 'bg-cyan-500';
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

function inferTaskStatus(message: ChatMessage, result: PresentationResult | null) {
  const action = message.meta?.action_required;
  const actionType = String(action?.type || '');
  const realtimeSync = String(message.meta?.realtime_sync || '');
  if (actionType === 'confirmation_required') return 'awaiting_confirmation';
  if (actionType === 'login_required') return 'waiting_login';
  const mode = String(message.meta?.mode || '');
  if (mode === 'background_worker') return 'queued';
  if (mode === 'chat_only_blocked') return 'paused';
  return String(result?.status || metaRecord(message.meta?.task_card).status || message.meta?.status || 'planning');
}

function taskTitle(message: ChatMessage, result: PresentationResult | null) {
  const card = message.meta?.task_card;
  if (card && typeof card === 'object' && 'title' in card) return String((card as { title?: unknown }).title || 'GIS 工具任务');
  const summary = String(result?.concise_summary || message.meta?.execution_summary?.summary || '').trim();
  if (summary) return summary.length > 42 ? `${summary.slice(0, 42)}...` : summary;
  const goal = String(metaRecord(message.meta?.plan).primary_goal || message.meta?.task_type || '').replace(/_/g, ' ').trim();
  if (goal) return goal;
  return 'GIS 工具任务';
}

function taskSummary(message: ChatMessage, result: PresentationResult | null) {
  if (result?.error_summary) return result.error_summary;
  if (result?.clarification_question) return result.clarification_question;
  if (result?.concise_summary) return result.concise_summary;
  const card = message.meta?.task_card;
  if (card && typeof card === 'object' && 'summary' in card) return String((card as { summary?: unknown }).summary || '');
  const summary = String(message.meta?.execution_summary?.summary || '').trim();
  return summary || '任务状态已更新。';
}

type AgentProcessStep = {
  id: string;
  title: string;
  detail: string;
  status?: string;
  toolName?: string;
};

function userReadableStatus(status = '') {
  const normalized = String(status || '').toLowerCase();
  if (['success', 'completed', 'complete'].includes(normalized)) return 'succeeded';
  return normalized || '';
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const text = String(value || '').trim();
    if (text) return text;
  }
  return '';
}

function countLabel(count: number, unit: string) {
  return count > 0 ? `${count} 个${unit}` : '';
}

function buildAgentProcessSteps(message: ChatMessage, result: PresentationResult | null, status: string): AgentProcessStep[] {
  const cardMeta = metaRecord(message.meta?.task_card);
  const managementView = metaRecord(message.meta?.management_view || message.meta?.download_management_view);
  const executionSummary = metaRecord(message.meta?.execution_summary);
  const action = metaRecord(message.meta?.action_required);
  const activeStep = firstText(cardMeta.current_step, managementView.current_step, message.meta?.current_step, managementView.action_state, action.message);
  const executed = (result?.executed_steps || []).filter((step) => step?.step_id || step?.tool_name);
  const artifactCount = (result?.artifact_refs || []).length + (result?.image_refs || []).length;
  const layerCount = (result?.map_layer_refs || []).length;
  const tableCount = (result?.table_refs || []).length;
  const dataSourceCount = (result?.data_sources || []).length;
  const outputParts = [
    countLabel(artifactCount, '文件'),
    countLabel(layerCount, '地图图层'),
    countLabel(tableCount, '表格'),
  ].filter(Boolean);
  const running = ['planning', 'queued', 'running', 'waiting_login', 'awaiting_confirmation', 'paused'].includes(String(status || '').toLowerCase());
  const terminal = ['succeeded', 'failed', 'blocked', 'cancelled', 'canceled'].includes(String(status || '').toLowerCase());
  const baseStatus = terminal ? 'succeeded' : 'running';
  const steps: AgentProcessStep[] = [
    {
      id: 'receive',
      title: '接收任务',
      detail: '读取你的请求，识别目标区域、数据类型、制图或 GIS 工具需求。',
      status: baseStatus,
    },
    {
      id: 'plan',
      title: '制定执行计划',
      detail: firstText(
        executionSummary.summary,
        cardMeta.summary,
        '拆解为数据检查、参数校验、工具调用、成果整理和回复生成。'
      ),
      status: baseStatus,
    },
    {
      id: 'validate',
      title: '正在检查输入数据',
      detail: dataSourceCount > 0
        ? `检查 ${dataSourceCount} 个数据源的会话归属、字段、坐标系、范围和必要参数。`
        : '检查工作区数据、会话、文件、字段、坐标系和必要参数。',
      status: executed.length || terminal ? 'succeeded' : (running ? 'running' : status),
    },
  ];

  if (executed.length) {
    executed.slice(0, 6).forEach((step, index) => {
      const toolName = String(step.tool_name || '').trim();
      const stepId = String(step.step_id || '').trim();
      steps.push({
        id: stepId || toolName || `execute-${index + 1}`,
        title: readableStepLabel(toolName || stepId || `步骤 ${index + 1}`),
        detail: toolName
          ? `调用工具 ${toolName}，执行 ${stepId || `第 ${index + 1} 个处理步骤`}。`
          : `执行 ${stepId || `第 ${index + 1} 个处理步骤`}。`,
        status: userReadableStatus(step.status || status),
        toolName,
      });
    });
  } else {
    steps.push({
      id: 'execute',
      title: '调用工具或工作流',
      detail: activeStep || '等待后端返回具体工具步骤；实时事件到达后会继续更新这里。',
      status: running ? 'running' : status,
    });
  }

  steps.push({
    id: 'register-results',
    title: '注册成果与地图图层',
    detail: outputParts.length
      ? `把 ${outputParts.join('、')} 绑定到当前会话，供地图面板、结果面板和下载按钮使用。`
      : '等待工具产物返回后，注册 artifact、地图图层、表格和预览资源。',
    status: outputParts.length || status === 'succeeded' ? 'succeeded' : (terminal ? status : 'queued'),
  });
  steps.push({
    id: 'respond',
    title: '生成回复和下一步建议',
    detail: firstText(
      result?.concise_summary,
      result?.next_action_suggestions?.[0] ? `整理结果摘要，并给出下一步建议：${result.next_action_suggestions[0]}` : '',
      '汇总执行结果、风险提示、可下载成果和可继续操作。'
    ),
    status: terminal ? status : 'queued',
  });
  return steps;
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





function numberFrom(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function TaskStatusCard({
  message,
  result,
  sessionId,
  resumeReady,
  onLogin,
  onResume,
  onCancel,
  onRetry,
  onClarification,
  onConfirmAction,
  onDeleted,
}: {
  message: ChatMessage;
  result: PresentationResult | null;
  sessionId?: string;
  resumeReady?: boolean;
  onLogin?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  onRetry?: (jobId: string) => void;
  onClarification?: (value: string, label: string) => void;
  onConfirmAction?: (prompt: string, confirmedActionId: string) => void;
  onDeleted?: (artifactId: string) => void;
}) {
  const action = message.meta?.action_required;
  const confirmationPrompt = String(action?.confirmation_prompt || '');
  const confirmedActionId = String(action?.confirmed_action_id || '');
  const presentation = buildTaskCardPresentation({ message, result });
  const status = presentation.status;
  const steps = buildAgentProcessSteps(message, result, status);
  const cardMeta = metaRecord(message.meta?.task_card);
  const managementView = metaRecord(message.meta?.management_view || message.meta?.download_management_view);
  const executionSummary = metaRecord(message.meta?.execution_summary);
  const jobId = String(action?.job_id || managementView.task_id || managementView.job_id || cardMeta.task_id || message.meta?.job_id || message.meta?.task_id || '');
  const availableActions = Array.isArray(managementView.available_actions) ? managementView.available_actions : [];
  const actionType = String(action?.type || '');
  const realtimeSync = String(message.meta?.realtime_sync || '');
  const progress = presentation.progress;
  const elapsedMs = numberFrom(cardMeta.elapsed_ms ?? message.meta?.elapsed_ms ?? executionSummary.elapsed_ms);
  const elapsedLabel = elapsedMs !== null && elapsedMs > 0 ? `${Math.max(1, Math.round(elapsedMs / 1000))} 秒` : '';
  const activeStep = presentation.currentStep || String(cardMeta.current_step || managementView.current_step || message.meta?.current_step || managementView.action_state || '').trim();
  const highlights = (result?.result_highlights || []).slice(0, 4);
  const dataSources = (result?.data_sources || []).slice(0, 4);
  const diagnostics = {
    status,
    reason: message.meta?.reason,
    warnings: result?.warnings || [],
    error_summary: result?.error_summary || '',
    next_actions: result?.next_action_suggestions || [],
  };
  const showTechnicalDetails = technicalDetailsEnabled();
  return (
    <section data-testid="task-status-card" className="agent-task-card relative mt-3 overflow-hidden rounded-[24px] border border-slate-200/85 bg-white/92 shadow-[0_22px_54px_rgba(15,23,42,.12)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/72">
      <div className={cn('h-1.5 bg-gradient-to-r', statusAccent(status))} />
      <div className={cn('task-card-status-spine absolute bottom-4 left-2 top-5 w-1 rounded-full', statusSpine(status))} />
      <div className="space-y-4 p-4">
        <div data-testid="task-card-a3-header" className="flex flex-wrap items-start justify-between gap-3 rounded-[20px] border border-slate-100 bg-slate-50/72 p-3 pl-4 dark:border-slate-800 dark:bg-slate-900/42">
          <div className="task-card-a3-identity flex min-w-0 flex-1 gap-3">
            <div className={cn('grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br text-white shadow-lg', statusAccent(status))}>
              <StatusIcon status={status} />
            </div>
            <div className="min-w-0">
              <div className="text-[11px] font-black uppercase tracking-[0.12em] text-slate-400">GIS 任务</div>
              <div className="mt-0.5 text-base font-black leading-6 text-slate-950 dark:text-slate-50">{taskTitle(message, result)}</div>
              <div className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{taskSummary(message, result)}</div>
            </div>
          </div>
          <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-black', statusTone(status))}>
            <StatusIcon status={status} />{statusLabel(status)}
          </span>
          {realtimeSync && <span className="inline-flex shrink-0 items-center rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-black text-slate-500 dark:bg-slate-800 dark:text-slate-300">{realtimeSync === 'live' ? '实时同步' : realtimeSync === 'connecting' ? '正在连接' : '定时同步'}</span>}
        </div>

        <div className="grid gap-2 rounded-[18px] border border-slate-200/70 bg-slate-50/75 p-3 dark:border-slate-800 dark:bg-slate-900/45 sm:grid-cols-3">
          <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <Gauge size={14} className="text-blue-600 dark:text-cyan-300" />
            <span className="font-bold">进度</span>
            <span>{progress !== null ? `${Math.max(0, Math.min(100, progress))}%` : '等待真实进度'}</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <Activity size={14} className="text-blue-600 dark:text-cyan-300" />
            <span className="font-bold">当前</span>
            <span>{activeStep || statusLabel(status)}</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <RefreshCcw size={14} className="text-blue-600 dark:text-cyan-300" />
            <span className="font-bold">耗时</span>
            <span>{elapsedLabel || '后端未提供'}</span>
          </div>
          {progress !== null && (
            <div className="col-span-full h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div className={cn('h-full rounded-full bg-gradient-to-r transition-all', statusAccent(status))} style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
            </div>
          )}
        </div>

        <TaskThinkingSummary thinking={presentation.thinking} />

        <TaskProcessTimeline steps={steps} overallStatus={status} />

        {(highlights.length > 0 || dataSources.length > 0) && (
          <div className="grid gap-2 sm:grid-cols-2">
            {highlights.map((item) => <div key={stableTextKey('highlight', item)} className="rounded-2xl bg-emerald-50 px-3 py-2 text-xs font-bold leading-5 text-emerald-800 dark:bg-emerald-950/25 dark:text-emerald-200">{item}</div>)}
            {dataSources.map((item) => <div key={stableTextKey('source', item)} className="rounded-2xl bg-slate-50 px-3 py-2 text-xs font-bold leading-5 text-slate-600 dark:bg-slate-900/60 dark:text-slate-300">数据：{item}</div>)}
          </div>
        )}

        {Boolean(result?.warnings?.length) && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            {result?.warnings?.slice(0, 4).map((item) => <div key={stableTextKey('warning', item)}>{item}</div>)}
          </div>
        )}
        {result?.error_summary && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{result.error_summary}</div>}
        {result?.clarification_question && <div className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-200">{result.clarification_question}</div>}

        <TaskActionBar
          action={action}
          status={status}
          actionType={actionType}
          availableActions={availableActions}
          jobId={jobId}
          confirmationPrompt={confirmationPrompt}
          confirmedActionId={confirmedActionId}
          resumeReady={resumeReady}
          onLogin={onLogin}
          onResume={onResume}
          onCancel={onCancel}
          onRetry={onRetry}
          onClarification={onClarification}
          onConfirmAction={onConfirmAction}
        />

        {result && (
          <div data-testid="task-card-result-dock" className="rounded-[20px] border border-slate-100 bg-white/72 p-2 dark:border-slate-800 dark:bg-slate-950/28">
            <div className="mb-1 px-1 text-[10px] font-black text-slate-400 dark:text-slate-500">结果产物</div>
            <ResultGroups result={result} sessionId={sessionId} onDeleted={onDeleted} />
          </div>
        )}
        <TaskDiagnosticsDetails
          status={status}
          result={result}
          diagnostics={diagnostics}
          showTechnicalDetails={showTechnicalDetails}
        />
      </div>
    </section>
  );
}
