import { Activity, AlertTriangle, Check, ChevronDown, Clipboard, Copy, Database, Download, FileBarChart, Gauge, Image as ImageIcon, Layers, ListChecks, LogIn, Package, PauseCircle, Play, RefreshCcw, ShieldCheck, XCircle } from 'lucide-react';
import { isValidElement, useEffect, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import { type ChatArtifact, type ChatMessage, type PresentationResult, type UserFacingResult } from '@/lib/api';
import { cn } from '@/lib/cn';
import { ArtifactDownloadCard } from './ArtifactDownloadCard';
import { buildTaskCardPresentation, type TaskThinkingPresentation } from './chat/taskCardModel';

function useCopyToast() {
  const [copied, setCopied] = useState(false);
  const copyText = async (text: string) => {
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2400);
    try {
      await navigator.clipboard.writeText(String(text || ''));
    } catch {
      const target = document.createElement('textarea');
      target.value = String(text || '');
      target.setAttribute('readonly', 'true');
      target.style.position = 'fixed';
      target.style.left = '-9999px';
      document.body.appendChild(target);
      target.select();
      document.execCommand('copy');
      target.remove();
    }
  };
  return { copied, copyText };
}

function CopyButton({ text, label, testId }: { text: string; label: string; testId?: string }) {
  const { copied, copyText } = useCopyToast();
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        copyText(text);
      }}
      className={cn('chat-copy-button', copied && 'is-copied')}
      title={copied ? '已复制' : label}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? '已复制' : label}</span>
    </button>
  );
}

const MARKDOWN_COMPONENTS = {
  code({ inline, className, children, node: _node, ...props }: any) {
    if (inline) {
      return <code className="chat-inline-code" {...props}>{children}</code>;
    }
    return <code className={className} {...props}>{children}</code>;
  },
  pre({ children }: { children?: ReactNode }) {
    const child = Array.isArray(children) ? children[0] : children;
    const codeProps = isValidElement(child)
      ? child.props as { className?: string; children?: ReactNode }
      : {};
    const value = String(codeProps.children || '').replace(/\n$/, '');
    const lang = /language-([\w-]+)/.exec(codeProps.className || '')?.[1] || 'code';
    return (
      <div className="chat-code-block">
        <div className="chat-code-toolbar">
          <span>{lang}</span>
          <CopyButton text={value} label="复制代码" testId="copy-code" />
        </div>
        <pre>{children}</pre>
      </div>
    );
  },
  table({ children }: { children?: ReactNode }) {
    return <div className="chat-table-wrap"><table>{children}</table></div>;
  },
};

function MarkdownBlocks({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={MARKDOWN_COMPONENTS}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function artifactsFromMessage(message: ChatMessage): ChatArtifact[] {
  const seen = new Set<string>();
  return (message.meta?.artifacts || []).filter((item): item is ChatArtifact => {
    if (!item?.artifact_id || seen.has(item.artifact_id)) return false;
    seen.add(item.artifact_id);
    return true;
  });
}

function userFacingResultFromMessage(message: ChatMessage): UserFacingResult | null {
  const result = message.meta?.user_facing_result;
  return result && typeof result === 'object' ? result : null;
}

function presentationResultFromMessage(message: ChatMessage): PresentationResult | null {
  const result = message.meta?.presentation_result;
  return result && typeof result === 'object' ? result : null;
}

function artifactKey(artifact: ChatArtifact) {
  return artifact.artifact_id || artifact.filename || artifact.title || 'artifact';
}

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

function AgentProcessTimeline({ steps, overallStatus }: { steps: AgentProcessStep[]; overallStatus: string }) {
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

function TaskThinkingSummary({ thinking }: { thinking: TaskThinkingPresentation }) {
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

function numberFrom(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function artifactFromRef(ref: { artifact_id: string; title?: string; type?: string; source_step_id?: string; source_tool?: string }, kind = ''): ChatArtifact {
  return {
    artifact_id: ref.artifact_id,
    title: ref.title || ref.artifact_id,
    name: ref.title || ref.artifact_id,
    type: ref.type || kind,
    kind: kind || ref.type || 'artifact',
    source: { tool_name: ref.source_tool, workflow_id: ref.source_step_id },
  };
}

function presentationArtifacts(result: PresentationResult) {
  const seen = new Set<string>();
  const add = (artifact: ChatArtifact) => {
    if (!artifact.artifact_id || seen.has(artifact.artifact_id)) return null;
    seen.add(artifact.artifact_id);
    return artifact;
  };
  return [
    ...(result.artifact_refs || []).map((ref) => add(artifactFromRef(ref))).filter(Boolean) as ChatArtifact[],
    ...(result.image_refs || []).map((ref) => add(artifactFromRef({ ...ref, type: 'image' }, 'image'))).filter(Boolean) as ChatArtifact[],
  ];
}

function groupPresentationArtifacts(result: PresentationResult) {
  const artifacts = presentationArtifacts(result);
  const imageIds = new Set((result.image_refs || []).map((item) => item.artifact_id));
  const modelOrReport = artifacts.filter((artifact) => /model|report|metrics|pdf|md|json/i.test(`${artifact.type || ''} ${artifact.title || ''}`));
  const images = artifacts.filter((artifact) => imageIds.has(artifact.artifact_id) || /image|plot|png|jpg|jpeg|webp/i.test(`${artifact.type || ''} ${artifact.title || ''}`));
  const data = artifacts.filter((artifact) => !modelOrReport.some((item) => item.artifact_id === artifact.artifact_id) && !images.some((item) => item.artifact_id === artifact.artifact_id));
  const recommended = artifacts.slice(0, 5);
  return [
    { id: 'recommended', title: '推荐查看', icon: ListChecks, artifacts: recommended },
    { id: 'data', title: '数据结果', icon: Database, artifacts: data },
    { id: 'images', title: '图像预览', icon: ImageIcon, artifacts: images },
    { id: 'models', title: '模型与报告', icon: FileBarChart, artifacts: modelOrReport },
  ];
}

function ResultGroups({
  result,
  sessionId,
  onDeleted,
}: {
  result: PresentationResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const groups = groupPresentationArtifacts(result);
  const allArtifacts = presentationArtifacts(result);
  const visibleGroups = groups.map((group) => ({ ...group, artifacts: showAll ? group.artifacts : group.artifacts.slice(0, group.id === 'recommended' ? 5 : 3) }));
  const visibleNextActions = (result.next_action_suggestions || []).slice(0, showAll ? 8 : 3);
  if (!allArtifacts.length && !(result.map_layer_refs || []).length && !(result.table_refs || []).length && !visibleNextActions.length) return null;
  return (
    <section data-testid="result-groups" className="mt-4 space-y-3 rounded-[20px] border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/28">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-2xl bg-white text-blue-600 shadow-sm dark:bg-slate-900 dark:text-cyan-300">
            <Package size={15} />
          </div>
          <div>
            <div className="text-sm font-black text-slate-900 dark:text-slate-100">任务结果</div>
            <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              {allArtifacts.length} 个文件 · {(result.map_layer_refs || []).length} 个图层 · {(result.table_refs || []).length} 个表格
            </div>
          </div>
        </div>
        {allArtifacts.length > 5 && (
          <button type="button" onClick={() => setShowAll((value) => !value)} className="chat-copy-button">
            <ChevronDown size={13} /> {showAll ? '收起全部结果' : '展开全部结果'}
          </button>
        )}
      </div>
      {allArtifacts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {allArtifacts[0] && <ArtifactDownloadCard artifact={{ ...allArtifacts[0], title: `下载推荐结果：${allArtifacts[0].title || allArtifacts[0].artifact_id}` }} sessionId={sessionId} onDeleted={onDeleted} />}
          {allArtifacts.length > 1 && (
            <button type="button" onClick={() => setShowAll(true)} className="chat-copy-button">
              <Download size={13} /> 下载全部结果
            </button>
          )}
        </div>
      )}
      {visibleGroups.map((group) => {
        const Icon = group.icon;
        if (!group.artifacts.length) return null;
        return (
          <div key={group.id} data-testid={`result-group-${group.id}`} className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 dark:border-slate-800 dark:bg-slate-950/35">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-black text-slate-600 dark:text-slate-300">
              <span className="inline-flex items-center gap-2"><Icon size={14} />{group.title}</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500 dark:bg-slate-900 dark:text-slate-400">{group.artifacts.length}</span>
            </div>
            <div className="artifact-download-list">
              {group.artifacts.map((artifact) => (
                <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
              ))}
            </div>
          </div>
        );
      })}
      {Boolean(result.map_layer_refs?.length) && (
        <div className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
          <div className="mb-1 flex items-center gap-2 font-black"><Layers size={14} />地图图层</div>
          {result.map_layer_refs?.slice(0, showAll ? 20 : 5).map((layer) => <div key={layer.layer_id}>{layer.name || layer.layer_id}</div>)}
        </div>
      )}
      {Boolean(result.table_refs?.length) && (
        <div className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
          <div className="mb-1 flex items-center gap-2 font-black"><Database size={14} />表格结果</div>
          {result.table_refs?.slice(0, showAll ? 20 : 5).map((table) => <div key={table.table_id}>{table.title || table.table_id}</div>)}
        </div>
      )}
      {visibleNextActions.length > 0 && (
        <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-3 text-xs leading-5 text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/25 dark:text-blue-200">
          <div className="mb-1 flex items-center gap-2 font-black"><ListChecks size={14} />下一步建议</div>
          {visibleNextActions.map((item) => <div key={stableTextKey('next-action', item)}>• {item}</div>)}
        </div>
      )}
    </section>
  );
}

function TaskStatusCard({
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
          <div className="flex min-w-0 flex-1 gap-3">
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

        <AgentProcessTimeline steps={steps} overallStatus={status} />

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

        <div className="flex flex-wrap gap-2 rounded-[18px] border border-slate-200/70 bg-white/70 p-2 dark:border-slate-800 dark:bg-slate-950/28">
          {action?.type === 'confirmation_required' && confirmationPrompt && confirmedActionId && (
            <button type="button" onClick={() => onConfirmAction?.(confirmationPrompt, confirmedActionId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700">
              <ShieldCheck size={14} />确认执行
            </button>
          )}
          {action?.type === 'login_required' && !resumeReady && <button type="button" onClick={() => onLogin?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><LogIn size={14} />去登录</button>}
          {action?.type === 'login_required' && resumeReady && <button type="button" onClick={() => onResume?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"><Play size={14} />登录后继续</button>}
          {jobId && canCancelTask(status, actionType, availableActions) && <button type="button" onClick={() => onCancel?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-coral"><XCircle size={14} />取消</button>}
          {jobId && canRetryTask(status, availableActions) && <button type="button" onClick={() => onRetry?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><RefreshCcw size={14} />重试</button>}
          {action?.type === 'clarification_required' && Array.isArray(action.options) && action.options.map((option) => (
            <button key={option.value} type="button" onClick={() => onClarification?.(option.value, option.label)} className="glass-button px-3 py-2 text-xs font-black">{option.label}</button>
          ))}
          {!action?.type && status === 'succeeded' && <span className="inline-flex items-center gap-1.5 px-2 py-2 text-xs font-bold text-slate-500 dark:text-slate-400"><Check size={14} />结果已生成</span>}
        </div>

        {result && (
          <div data-testid="task-card-result-dock" className="rounded-[20px] border border-slate-100 bg-white/72 p-2 dark:border-slate-800 dark:bg-slate-950/28">
            <div className="mb-1 px-1 text-[10px] font-black text-slate-400 dark:text-slate-500">结果产物</div>
            <ResultGroups result={result} sessionId={sessionId} onDeleted={onDeleted} />
          </div>
        )}
        <details className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-900/60">
          <summary className="cursor-pointer font-bold text-slate-600 dark:text-slate-300">查看详情</summary>
          <div className="mt-2 space-y-1 text-[11px] leading-5 text-slate-500 dark:text-slate-400">
            <div>状态：{statusLabel(status)}</div>
            {result?.executed_steps?.map((step) => <div key={`${step.step_id || step.tool_name}`}>{readableStepLabel(step.tool_name || step.step_id)}：{statusLabel(step.status || '')}</div>)}
            {showTechnicalDetails && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap">{JSON.stringify(diagnostics, null, 2)}</pre>}
          </div>
        </details>
      </div>
    </section>
  );
}

function UserFacingResultCard({
  result,
  sessionId,
  onDeleted
}: {
  result: UserFacingResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const primary = (result.primary_artifacts || []).filter((item) => item?.artifact_id);
  const previews = (result.preview_artifacts || []).filter((item) => item?.artifact_id);
  const primaryIds = new Set(primary.map((item) => item.artifact_id));
  const previewOnly = previews.filter((item) => !primaryIds.has(item.artifact_id));
  const groups = result.grouped_artifacts || [];
  const bundles = [result.download_bundle?.recommended, result.download_bundle?.all].filter((item): item is ChatArtifact => Boolean(item?.artifact_id));
  const debug = { ...(result.technical_details || {}), ...(result.debug || {}) };
  const showTechnicalDetails = technicalDetailsEnabled();

  return (
    <section data-testid="user-facing-result-card" className="mt-3 space-y-3 rounded-2xl border border-slate-200/85 bg-white/70 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/35">
      {result.summary && <div className="text-sm font-bold leading-6 text-slate-800 dark:text-slate-100">{result.summary}</div>}
      {Boolean(result.key_findings?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.key_findings?.slice(0, 6).map((item, index) => (
            <div key={`${item}-${index}`} className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700 dark:bg-slate-900 dark:text-slate-200">{item}</div>
          ))}
        </div>
      )}
      {Boolean(result.insights?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.insights?.slice(0, 5).map((item, index) => <div key={`${item}-${index}`}>• {item}</div>)}
        </div>
      )}
      {Boolean(result.warnings?.length) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {result.warnings?.slice(0, 4).map((item, index) => <div key={`${item}-${index}`}>• {item}</div>)}
        </div>
      )}
      {bundles.length > 0 && (
        <div data-testid="download-bundle-actions" className="grid gap-2">
          {bundles.map((artifact) => (
            <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
          ))}
        </div>
      )}
      {(primary.length > 0 || previewOnly.length > 0) && (
        <div className="artifact-download-list">
          {[...primary, ...previewOnly].map((artifact) => (
            <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
          ))}
        </div>
      )}
      {showAll && groups.length > 0 && (
        <div data-testid="artifact-group-list" className="space-y-3">
          {groups.map((group) => (
            <div key={group.group} className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-black text-slate-500 dark:text-slate-400"><Package size={13} />{group.group}</div>
              {(group.artifacts || []).filter((item) => item?.artifact_id).map((artifact) => (
                <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
              ))}
            </div>
          ))}
        </div>
      )}
      {groups.length > 0 && (
        <button type="button" onClick={() => setShowAll((value) => !value)} className="chat-copy-button">
          {showAll ? '收起文件' : '展开全部文件'}
        </button>
      )}
      {Boolean(result.next_actions?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.next_actions?.slice(0, 5).map((item, index) => <div key={`${item}-${index}`}>下一步：{item}</div>)}
        </div>
      )}
      {showTechnicalDetails && Object.keys(debug).length > 0 && (
        <details data-testid="technical-details" className="rounded-xl border border-slate-200 bg-slate-50 p-2 text-xs dark:border-slate-800 dark:bg-slate-900/60">
          <summary className="cursor-pointer font-bold text-slate-600 dark:text-slate-300">查看技术详情</summary>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-500 dark:text-slate-400">{JSON.stringify(debug, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}

function PresentationResultCard({
  result,
  sessionId,
  onDeleted,
}: {
  result: PresentationResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const status = String(result.status || '');
  return (
    <section data-testid="presentation-result-card" className="mt-3 space-y-3 rounded-2xl border border-slate-200/85 bg-white/75 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn(
          'rounded-full px-2 py-0.5 text-[10px] font-black uppercase tracking-wide',
          status === 'succeeded' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200',
          status === 'failed' && 'bg-rose-50 text-rose-700 dark:bg-rose-950/35 dark:text-rose-200',
          status === 'blocked' && 'bg-amber-50 text-amber-700 dark:bg-amber-950/35 dark:text-amber-200',
          status === 'awaiting_confirmation' && 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200',
          status === 'running' && 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
        )}>{statusLabel(status)}</span>
        {result.schema_version && <span className="text-[11px] font-semibold text-slate-400">{result.schema_version}</span>}
      </div>
      {result.concise_summary && <div className="text-sm font-bold leading-6 text-slate-800 dark:text-slate-100">{result.concise_summary}</div>}
      {Boolean(result.executed_steps?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.executed_steps?.slice(0, 6).map((step, index) => (
            <div key={`${step.step_id || index}-${step.tool_name || ''}`} className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <div>{step.step_id || step.tool_name || `step ${index + 1}`}</div>
              <div className="mt-0.5 text-[11px] font-semibold text-slate-500">{step.tool_name || 'tool'} · {step.status || 'unknown'}</div>
            </div>
          ))}
        </div>
      )}
      {Boolean(result.result_highlights?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.result_highlights?.slice(0, 8).map((item, index) => (
            <div key={`${item}-${index}`} className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200">{item}</div>
          ))}
        </div>
      )}
      <ResultGroups result={result} sessionId={sessionId} onDeleted={onDeleted} />
      {Boolean(result.warnings?.length) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {result.warnings?.slice(0, 4).map((item, index) => <div key={`${item}-${index}`}>{item}</div>)}
        </div>
      )}
      {result.error_summary && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{result.error_summary}</div>}
      {result.clarification_question && <div className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-200">{result.clarification_question}</div>}
      {Boolean(result.next_action_suggestions?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.next_action_suggestions?.slice(0, 5).map((item) => <div key={stableTextKey('presentation-next', item)}>下一步：{item}</div>)}
        </div>
      )}
    </section>
  );
}

export function ChatMessageRenderer({
  message,
  content,
  isUser = false,
  isSystem = false,
  resumeReady = false,
  onLogin,
  onResume,
  onCancel,
  onRetry,
  onClarification,
  onConfirmAction,
  sessionId
}: {
  message: ChatMessage;
  content: string;
  isUser?: boolean;
  isSystem?: boolean;
  resumeReady?: boolean;
  onLogin?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  onRetry?: (jobId: string) => void;
  onClarification?: (value: string, label: string) => void;
  onConfirmAction?: (prompt: string, confirmedActionId: string) => void;
  sessionId?: string;
}) {
  const artifacts = artifactsFromMessage(message);
  const presentationResult = presentationResultFromMessage(message);
  const userResult = userFacingResultFromMessage(message);
  const resultPreference = presentationResult || userResult;
  const [deletedArtifactIds, setDeletedArtifactIds] = useState<Set<string>>(() => new Set());
  const visibleArtifacts = artifacts.filter((artifact) => !deletedArtifactIds.has(artifact.artifact_id));
  const [selection, setSelection] = useState('');
  const { copied, copyText } = useCopyToast();
  const action = message.meta?.action_required;
  const jobId = String(action?.job_id || '');
  const confirmationPrompt = String(action?.confirmation_prompt || '');
  const confirmedActionId = String(action?.confirmed_action_id || '');
  const mode = String(message.meta?.mode || '');
  const reason = String(message.meta?.reason || '');
  const streaming = Boolean(message.meta?.streaming);
  const interactionType = String(message.meta?.interaction_type || '');
  const hasTaskCard = !isUser && !isSystem && reason !== 'tool_mode_required' && (
    interactionType === 'tool_task'
    ||
    Boolean(message.meta?.task_card)
    || Boolean(message.meta?.management_view)
    || Boolean(message.meta?.download_management_view)
    || ['background_worker', 'validated_download_executor', 'coordinated_workflow', 'validated_workflow_executor', 'validated_tool_executor'].includes(mode)
    || ['confirmation_required', 'login_required'].includes(String(action?.type || ''))
  );
  const showConversationText = !hasTaskCard || (!presentationResult && !action);

  useEffect(() => {
    const onSelectionChange = () => setSelection(window.getSelection()?.toString().trim() || '');
    document.addEventListener('selectionchange', onSelectionChange);
    return () => document.removeEventListener('selectionchange', onSelectionChange);
  }, []);

  return (
    <div className="chat-message-renderer">
      {!hasTaskCard && streaming && !content && <div data-testid="chat-streaming-placeholder" className="inline-flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-500 dark:bg-slate-900/70 dark:text-slate-300"><span className="h-2 w-2 animate-pulse rounded-full bg-cyan-500" />正在生成回答</div>}
      {showConversationText && <MarkdownBlocks content={content} />}
      {!hasTaskCard && streaming && content && <span data-testid="chat-streaming-cursor" className="ml-1 inline-block h-4 w-1.5 animate-pulse align-[-2px] bg-cyan-500" />}
      {hasTaskCard && (
        <TaskStatusCard
          message={message}
          result={presentationResult}
          sessionId={sessionId}
          resumeReady={resumeReady}
          onLogin={onLogin}
          onResume={onResume}
          onCancel={onCancel}
          onRetry={onRetry}
          onClarification={onClarification}
          onConfirmAction={onConfirmAction}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!hasTaskCard && presentationResult && (
        <PresentationResultCard
          result={presentationResult}
          sessionId={sessionId}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!presentationResult && resultPreference && (
        <UserFacingResultCard
          result={resultPreference as UserFacingResult}
          sessionId={sessionId}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!hasTaskCard && action?.type === 'login_required' && (
        <div data-testid="gscloud-login-required" className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-100/45 p-3 dark:bg-amber-400/10">
          <div className="text-sm font-black">需要登录地理空间数据云账号</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {!resumeReady && <button type="button" onClick={() => onLogin?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><LogIn size={14} />去登录</button>}
            {resumeReady && <button type="button" onClick={() => onResume?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"><Play size={14} />继续下载</button>}
            <button type="button" onClick={() => onCancel?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-coral"><XCircle size={14} />取消任务</button>
          </div>
        </div>
      )}
      {!hasTaskCard && action?.type === 'clarification_required' && Array.isArray(action.options) && (
        <div data-testid="download-clarification-options" className="mt-3 flex flex-wrap gap-2">
          {action.options.map((option) => <button key={option.value} type="button" onClick={() => onClarification?.(option.value, option.label)} className="glass-button px-3 py-2 text-xs font-black">{option.label}</button>)}
        </div>
      )}
      {!hasTaskCard && action?.type === 'confirmation_required' && confirmationPrompt && confirmedActionId && (
        <div data-testid="download-confirmation-required" className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-100/45 p-3 dark:bg-amber-400/10">
          <div className="text-sm font-black">需要确认后执行</div>
          <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">{String(action.message || '请确认产品、区域、账号、费用和覆盖风险后再继续。')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onConfirmAction?.(confirmationPrompt, confirmedActionId)}
              className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"
            >
              <ShieldCheck size={14} />确认执行
            </button>
          </div>
        </div>
      )}
      {!presentationResult && !userResult && visibleArtifacts.length > 0 && (
        <div data-testid="artifact-download-list" className="artifact-download-list">
          {visibleArtifacts.map((artifact) => (
            <ArtifactDownloadCard
              key={artifactKey(artifact)}
              artifact={artifact}
              sessionId={sessionId}
              onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
            />
          ))}
        </div>
      )}
      {!isUser && !isSystem && (
        <div data-testid="chat-message-actions" className="chat-message-actions">
          <CopyButton text={content} label="复制" testId="copy-message" />
          {selection && (
            <button
              type="button"
              className={cn('chat-copy-button', copied && 'is-copied')}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                copyText(selection);
              }}
              title="复制选中文本"
            >
              {copied ? <Check size={13} /> : <Clipboard size={13} />}
              <span>{copied ? '已复制' : '复制选中文本'}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
