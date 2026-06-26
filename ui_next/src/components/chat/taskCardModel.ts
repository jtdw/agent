type RecordLike = Record<string, unknown>;

export type TaskCardStatus =
  | 'planning'
  | 'awaiting_confirmation'
  | 'queued'
  | 'running'
  | 'waiting_login'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'blocked';

export type PublicProcessStep = {
  id: string;
  title: string;
  detail: string;
  status: TaskCardStatus | string;
};

export type TaskThinkingPresentation = {
  summary: string;
  steps: PublicProcessStep[];
  defaultExpanded: boolean;
};

export type TaskCardPresentation = {
  status: TaskCardStatus;
  progress: number | null;
  currentStep: string;
  thinking: TaskThinkingPresentation;
};

type BuildInput = {
  message: {
    role?: string;
    content?: string;
    meta?: RecordLike;
  };
  result?: RecordLike | null;
};

const SENSITIVE_PATTERNS = [
  /\.env/i,
  /storage_state/i,
  /cookie/i,
  /token\s*=/i,
  /traceback/i,
  /[A-Za-z]:\\[^\s，。；;]+/,
  /(?:\/[\w.-]+){2,}/,
];

function record(value: unknown): RecordLike {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as RecordLike : {};
}

function text(value: unknown): string {
  return String(value || '').trim();
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const candidate = sanitizePublicText(text(value));
    if (candidate) return candidate;
  }
  return '';
}

export function normalizeTaskStatus(value: unknown): TaskCardStatus {
  const raw = text(value).toLowerCase();
  if (['success', 'completed', 'complete', 'done'].includes(raw)) return 'succeeded';
  if (raw === 'canceled') return 'cancelled';
  if (raw === 'confirmation_required') return 'awaiting_confirmation';
  if (raw === 'login_required') return 'waiting_login';
  if (
    raw === 'planning'
    || raw === 'awaiting_confirmation'
    || raw === 'queued'
    || raw === 'running'
    || raw === 'waiting_login'
    || raw === 'paused'
    || raw === 'succeeded'
    || raw === 'failed'
    || raw === 'cancelled'
    || raw === 'blocked'
  ) {
    return raw;
  }
  return 'planning';
}

export function sanitizePublicText(value: string): string {
  let output = text(value);
  if (!output) return '';
  let redacted = false;
  for (const pattern of SENSITIVE_PATTERNS) {
    if (pattern.test(output)) {
      redacted = true;
      output = output.replace(pattern, '已隐藏敏感细节');
    }
  }
  output = output.replace(/\s+/g, ' ').trim();
  if (!output) return redacted ? '已隐藏敏感细节。' : '';
  return output;
}

function progressFrom(...values: unknown[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue;
    const number = Number(value);
    if (Number.isFinite(number)) return Math.max(0, Math.min(100, number));
  }
  return null;
}

function statusFrom(input: BuildInput): TaskCardStatus {
  const meta = record(input.message.meta);
  const result = record(input.result);
  const action = record(meta.action_required);
  const managementView = record(meta.management_view || meta.download_management_view);
  const card = record(meta.task_card);
  const actionType = text(action.type);
  if (actionType === 'confirmation_required') return 'awaiting_confirmation';
  if (actionType === 'login_required') return 'waiting_login';
  return normalizeTaskStatus(
    result.status
    || managementView.status
    || card.status
    || meta.status
    || 'planning'
  );
}

function readableToolStep(value = ''): string {
  const normalized = value.toLowerCase();
  if (!normalized) return '处理步骤';
  if (normalized.includes('workspace') || normalized.includes('context')) return '读取工作区上下文';
  if (normalized.includes('validate') || normalized.includes('check')) return '检查输入数据';
  if (normalized.includes('download') || normalized.includes('gscloud')) return '提交下载任务';
  if (normalized.includes('clip')) return '裁剪数据';
  if (normalized.includes('reproject')) return '检查并转换坐标系';
  if (normalized.includes('map')) return '生成地图图层';
  return value.replace(/_/g, ' ');
}

function publicProcessFromResult(result: RecordLike, status: TaskCardStatus): PublicProcessStep[] {
  const executed = Array.isArray(result.executed_steps) ? result.executed_steps : [];
  return executed.flatMap((step, index) => {
    const item = record(step);
    const toolName = text(item.tool_name);
    const stepId = text(item.step_id);
    const label = readableToolStep(toolName || stepId || `步骤 ${index + 1}`);
    const detail = toolName
      ? `调用工具 ${sanitizePublicText(toolName)}，执行 ${sanitizePublicText(stepId || `第 ${index + 1} 个处理步骤`)}。`
      : `执行 ${sanitizePublicText(stepId || `第 ${index + 1} 个处理步骤`)}。`;
    return [{
      id: stepId || toolName || `executed-${index + 1}`,
      title: label,
      detail,
      status: normalizeTaskStatus(item.status || status),
    }];
  });
}

function defaultPublicProcess(input: BuildInput, status: TaskCardStatus): PublicProcessStep[] {
  const meta = record(input.message.meta);
  const result = record(input.result);
  const card = record(meta.task_card);
  const managementView = record(meta.management_view || meta.download_management_view);
  const executionSummary = record(meta.execution_summary);
  const action = record(meta.action_required);
  const current = firstText(card.current_step, managementView.current_step, managementView.user_message, executionSummary.summary, result.error_summary);
  return [
    {
      id: 'read-context',
      title: '读取工作区上下文',
      detail: '读取当前会话、已上传数据、结果文件和地图图层状态。',
      status: ['planning', 'queued', 'running', 'awaiting_confirmation', 'waiting_login', 'succeeded'].includes(status) ? 'succeeded' : status,
    },
    {
      id: 'validate-input',
      title: '检查输入数据',
      detail: current || '检查字段、坐标系、范围、文件归属和必要参数。',
      status: ['running', 'waiting_login', 'awaiting_confirmation'].includes(status) ? 'running' : status,
    },
    {
      id: 'plan-or-wait',
      title: status === 'awaiting_confirmation' ? '等待确认后执行' : '生成处理计划',
      detail: status === 'awaiting_confirmation'
        ? firstText(action.message, '确认前不会执行下载、写入结果或消耗配额。')
        : '准备工具计划、成果注册和最终回复；实时事件到达后会继续更新。',
      status: status === 'awaiting_confirmation' ? 'awaiting_confirmation' : (status === 'succeeded' ? 'succeeded' : 'queued'),
    },
  ];
}

function thinkingSummary(status: TaskCardStatus, steps: PublicProcessStep[]): string {
  if (status === 'awaiting_confirmation') return '已生成执行计划，等待确认后再执行工具任务。';
  if (status === 'waiting_login') return '任务需要登录数据源账号，登录完成后可继续执行。';
  if (status === 'failed') return '任务无法继续，已整理失败原因和可执行的下一步。';
  if (status === 'succeeded') return '任务已完成，正在整理成果、地图图层和下一步建议。';
  const completed = steps.filter((step) => normalizeTaskStatus(step.status) === 'succeeded').length;
  return `正在检查输入数据，已完成 ${completed}/${Math.max(steps.length, 1)} 个阶段。`;
}

export function buildTaskCardPresentation(input: BuildInput): TaskCardPresentation {
  const meta = record(input.message.meta);
  const result = record(input.result);
  const card = record(meta.task_card);
  const managementView = record(meta.management_view || meta.download_management_view);
  const status = statusFrom(input);
  const progress = progressFrom(card.progress, managementView.progress, meta.progress);
  const resultSteps = publicProcessFromResult(result, status);
  const defaultSteps = defaultPublicProcess(input, status);
  const steps = resultSteps.length >= 2
    ? [
      defaultSteps[0],
      ...resultSteps,
      defaultSteps[2],
    ]
    : defaultSteps;
  return {
    status,
    progress,
    currentStep: firstText(card.current_step, managementView.current_step, managementView.user_message, result.error_summary),
    thinking: {
      summary: thinkingSummary(status, steps),
      steps,
      defaultExpanded: ['running', 'awaiting_confirmation', 'waiting_login', 'failed', 'blocked'].includes(status),
    },
  };
}
