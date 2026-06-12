export const DOWNLOAD_JOB_STATUS_KEYS = ['queued', 'running', 'waiting_login', 'waiting_manual', 'completed', 'failed', 'canceled'] as const;

export type DownloadJobStatus = typeof DOWNLOAD_JOB_STATUS_KEYS[number];

export type DownloadJobStatusMeta = {
  key: DownloadJobStatus;
  label: string;
  description: string;
  tone: 'waiting' | 'running' | 'blocked' | 'succeeded' | 'failed' | 'canceled';
};

export const DOWNLOAD_JOB_STATUS: Record<DownloadJobStatus, DownloadJobStatusMeta> = {
  queued: { key: 'queued', label: '等待中', description: '已进入任务队列', tone: 'waiting' },
  running: { key: 'running', label: '执行中', description: '任务正在运行', tone: 'running' },
  waiting_login: { key: 'waiting_login', label: '需要登录', description: '数据源登录态需要确认', tone: 'blocked' },
  waiting_manual: { key: 'waiting_manual', label: '需要处理', description: '需要人工处理后继续', tone: 'blocked' },
  completed: { key: 'completed', label: '成功', description: '任务已完成并通过基础校验', tone: 'succeeded' },
  failed: { key: 'failed', label: '失败', description: '任务运行失败', tone: 'failed' },
  canceled: { key: 'canceled', label: '已取消', description: '任务已取消', tone: 'canceled' }
};

export function isDownloadJobStatus(value: string): value is DownloadJobStatus {
  return (DOWNLOAD_JOB_STATUS_KEYS as readonly string[]).includes(value);
}
