import type { DownloadJob, WorkspaceArtifact } from '@/lib/api';

export type ProductTaskTone = 'idle' | 'waiting' | 'running' | 'blocked' | 'succeeded' | 'failed' | 'canceled';

export const DOWNLOAD_JOB_STATUS_KEYS = ['queued', 'running', 'waiting_login', 'waiting_manual', 'completed', 'failed', 'canceled'] as const;

const DOWNLOAD_JOB_STATUS = {
  queued: { key: 'queued', label: '等待中', description: '已进入任务队列', tone: 'waiting' },
  running: { key: 'running', label: '执行中', description: '任务正在运行', tone: 'running' },
  waiting_login: { key: 'waiting_login', label: '需要登录', description: '数据源登录态需要确认', tone: 'blocked' },
  waiting_manual: { key: 'waiting_manual', label: '需要处理', description: '需要人工处理后继续', tone: 'blocked' },
  completed: { key: 'completed', label: '成功', description: '任务已完成并通过基础校验', tone: 'succeeded' },
  failed: { key: 'failed', label: '失败', description: '任务运行失败', tone: 'failed' },
  canceled: { key: 'canceled', label: '已取消', description: '任务已取消', tone: 'canceled' }
} satisfies Record<(typeof DOWNLOAD_JOB_STATUS_KEYS)[number], ProductTaskStatus>;

function isDownloadJobStatus(value: string): value is (typeof DOWNLOAD_JOB_STATUS_KEYS)[number] {
  return (DOWNLOAD_JOB_STATUS_KEYS as readonly string[]).includes(value);
}

export type ProductTaskStatus = {
  key: string;
  label: string;
  description: string;
  tone: ProductTaskTone;
};

export type JobSummary = {
  total: number;
  active: number;
  running: number;
  waiting: number;
  succeeded: number;
  failed: number;
  canceled: number;
};

export type ConsoleArtifact = {
  artifactId: string;
  label: string;
  url: string;
  path: string;
  kind: 'report' | 'visual' | 'archive' | 'data' | 'artifact';
};

const TASK_STATUS: Record<string, ProductTaskStatus> = {
  draft: { key: 'draft', label: '草稿', description: '尚未启动', tone: 'idle' },
  idle: { key: 'idle', label: '就绪', description: '等待新任务', tone: 'idle' },
  validating: { key: 'validating', label: '预检中', description: '正在检查参数和登录态', tone: 'running' },
  queued: DOWNLOAD_JOB_STATUS.queued,
  running: DOWNLOAD_JOB_STATUS.running,
  waiting_login: DOWNLOAD_JOB_STATUS.waiting_login,
  waiting_manual: DOWNLOAD_JOB_STATUS.waiting_manual,
  completed: DOWNLOAD_JOB_STATUS.completed,
  success: { key: 'success', label: '成功', description: '任务已完成', tone: 'succeeded' },
  failed: DOWNLOAD_JOB_STATUS.failed,
  canceled: DOWNLOAD_JOB_STATUS.canceled,
  canceling: { key: 'canceling', label: '取消中', description: '正在取消任务', tone: 'running' },
  exporting: { key: 'exporting', label: '导出中', description: '正在打包结果', tone: 'running' }
};

export function normalizeTaskStatus(status?: string): ProductTaskStatus {
  const key = String(status || '').trim().toLowerCase();
  if (isDownloadJobStatus(key)) return DOWNLOAD_JOB_STATUS[key];
  return TASK_STATUS[key] || {
    key: key || 'unknown',
    label: key || '未知',
    description: '尚未识别的任务状态',
    tone: 'idle'
  };
}

export function summarizeJobs(jobs: Array<Pick<DownloadJob, 'status'>> = []): JobSummary {
  return jobs.reduce<JobSummary>((summary, job) => {
    const tone = normalizeTaskStatus(job.status).tone;
    summary.total += 1;
    if (tone === 'running') {
      summary.running += 1;
      summary.active += 1;
    } else if (tone === 'waiting' || tone === 'blocked') {
      summary.waiting += 1;
      summary.active += 1;
    } else if (tone === 'succeeded') {
      summary.succeeded += 1;
    } else if (tone === 'failed') {
      summary.failed += 1;
    } else if (tone === 'canceled') {
      summary.canceled += 1;
    }
    return summary;
  }, {
    total: 0,
    active: 0,
    running: 0,
    waiting: 0,
    succeeded: 0,
    failed: 0,
    canceled: 0
  });
}

export function groupArtifacts(artifacts: WorkspaceArtifact[] = []): ConsoleArtifact[] {
  return artifacts
    .map((artifact) => {
      const url = String(artifact.download_url || '');
      if (!url) return null;
      const label = String(artifact.name || artifact.path?.split(/[\\/]/).pop() || '结果文件');
      const lower = label.toLowerCase();
      let kind: ConsoleArtifact['kind'] = 'artifact';
      if (/\.(png|jpg|jpeg|webp|svg)$/i.test(lower)) kind = 'visual';
      else if (/\.(zip|7z|rar)$/i.test(lower)) kind = 'archive';
      else if (/\.(csv|xlsx|xls|md|txt|docx|pdf)$/i.test(lower)) kind = 'report';
      else if (/\.(geojson|json|tif|tiff|shp|gpkg)$/i.test(lower)) kind = 'data';
      return { artifactId: String(artifact.artifact_id || ''), label, url, path: String(artifact.path || ''), kind };
    })
    .filter((item): item is ConsoleArtifact => Boolean(item));
}

export function formatPercent(value?: number) {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}
