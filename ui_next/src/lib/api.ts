
import type { ChatContextPayload } from './chatContext';

export type TiandituConfig = {
  enabled: boolean;
  token_masked?: string;
  default_basemap?: string;
  subdomains: string[];
  matrix_set?: string;
  tile_url_templates: Record<string, string>;
  capabilities?: string[];
  setup_hint?: string;
};


export type StationPoint = {
  id: string;
  station_id: string;
  name: string;
  longitude: number;
  latitude: number;
  lng: number;
  lat: number;
  elevation_m?: number | null;
  depth_m?: number | null;
  depth_label?: string;
  sample_count: number;
  mean_sm?: number | null;
  min_sm?: number | null;
  max_sm?: number | null;
  first_time?: string;
  last_time?: string;
  source_file?: string;
  value?: string;
  risk?: 'low' | 'mid' | 'high' | 'unknown';
};

export type StationCollection = {
  source: string;
  source_name: string;
  preferred_depth?: string;
  year?: string;
  count: number;
  bounds: [number, number, number, number];
  center: [number, number];
  mean_sm?: number | null;
  stations: StationPoint[];
  geojson?: Record<string, unknown>;
  message?: string;
};

export type UserPlan = 'free' | 'basic' | 'pro' | 'team';
export type PaidPlan = 'pro' | 'team';

export type CommercialUser = {
  user_id: string;
  email: string;
  plan: UserPlan;
  plan_expires_at?: string;
  platform_monthly_quota?: number;
  platform_monthly_used?: number;
  own_daily_quota?: number;
  status?: string;
};

export type ChatMessage = {
  message_id?: number;
  session_id?: string;
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  meta?: Record<string, unknown> & { artifacts?: ChatArtifact[]; upload_summaries?: UploadSummary[]; action_required?: ChatActionRequired };
};

export type ChatActionRequired = {
  type: 'login_required' | 'clarification_required' | 'resume_ready' | string;
  provider?: string;
  job_id?: string;
  user_message?: string;
  actions?: string[];
  missing_parameters?: string[];
  recommended_defaults?: Record<string, unknown>;
  options?: Array<{ value: string; label: string }>;
};

export type DataSourceAccountStatus = {
  provider: 'gscloud';
  logged_in: boolean;
  account_mode: 'own';
  last_checked_at: string;
  expires_at?: string | null;
  masked_account?: string | null;
  storage_state_exists: boolean;
  health_status: string;
  user_message: string;
  pending?: boolean;
  login_state?: string;
  waiting_jobs?: DownloadJob[];
};

export type ChatArtifact = {
  artifact_id: string;
  filename: string;
  name?: string;
  title?: string;
  type?: string;
  kind?: string;
  display_path?: string;
  size_bytes?: number;
  size_kb?: number;
  mime_type?: string;
  created_at?: string;
  updated_at?: string;
  source?: {
    tool_name?: string;
    workflow_id?: string;
    message_id?: string;
  };
  preview_available?: boolean;
  download_url: string;
  metadata_url?: string;
  meta?: Record<string, unknown>;
};

export type ChatSession = {
  session_id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type ChatModelState = {
  session_id: string;
  route_mode: 'auto' | 'manual';
  selected_model: string;
  active_model?: string;
  models: Array<{ id: string; capability: 'text' | 'vision' }>;
};

export type AuthSession = {
  user: CommercialUser;
  session_id?: string;
  session_token?: string;
  expires_at?: string;
};

export type CurrentAuthSession = {
  authenticated: boolean;
  user: CommercialUser | null;
  session_id?: string;
  expires_at?: string;
};

export type WorkspaceArtifact = {
  artifact_id?: string;
  name?: string;
  path: string;
  type?: string;
  size?: number;
  updated_at?: string;
  download_url?: string;
};

export type WorkspaceMention = {
  id: string;
  name: string;
  mention: string;
  type: string;
  filename?: string;
  row_count?: number | null;
  column_count?: number | null;
  crs?: string;
};

export type ResultPanelFile = {
  artifact_id?: string;
  label: string;
  path?: string;
  download_url?: string;
  kind?: string;
};

export type ResultPanel = {
  has_results?: boolean;
  title?: string;
  files?: ResultPanelFile[];
  result_paths?: string[];
  recommendations?: string[];
};

export type ResultMapLayer = {
  id: string;
  name: string;
  type: 'vector' | 'raster';
  kind: 'dem' | 'boundary' | 'soil' | string;
  dataset_name?: string;
  artifact_id?: string;
  map_ready?: boolean;
  bounds?: [number, number, number, number];
  feature_count?: number;
  geojson?: GeoJSON.FeatureCollection;
  preview_url?: string;
  meta?: Record<string, unknown>;
};

import type { DownloadJobStatus } from './downloadStatus';

export type DownloadJob = {
  job_id: string;
  user_id?: string;
  source_key?: string;
  resource_type?: string;
  region?: string;
  account_mode?: string;
  output_name?: string;
  status?: DownloadJobStatus | string;
  state?: DownloadJobStatus | string;
  status_label?: string;
  message?: string;
  progress?: number;
  stage?: string;
  error_message?: string;
  output_path?: string;
  zip_path?: string;
  download_url?: string;
  charged?: number;
  quota_reserved?: number;
  retried_from_job_id?: string;
  artifacts?: ChatArtifact[];
  canceled_at?: string;
  pages_scanned?: number;
  candidate_count?: number;
  selected_count?: number;
  downloaded_count?: number;
  current_scene?: string;
  scan_stop_reason?: string;
  failure_diagnostic?: {
    code?: string;
    title?: string;
    user_message?: string;
    next_action?: string;
  };
  login_health?: Record<string, unknown>;
  region_resolution?: Record<string, unknown>;
  artifact_quality?: Array<Record<string, unknown>>;
  scene_status?: Record<string, unknown>;
  updated_at?: string;
  finished_at?: string;
};

export type LoginHealthResponse = {
  source_key: string;
  account_mode: string;
  login_health: {
    ok?: boolean;
    reason?: string;
    action?: string;
    path?: string;
    detail?: string;
    [key: string]: unknown;
  };
};

export type WorkspaceDashboard = {
  summary: string;
  datasets: Array<Record<string, unknown>>;
  artifacts: WorkspaceArtifact[];
  model_results?: Array<Record<string, unknown>>;
  activity: Array<Record<string, unknown>>;
  dataset_type_counts: Record<string, number>;
  runtime_status: Record<string, unknown>;
  capability_groups: Record<string, string[]>;
  suggestions: string[];
  database?: Record<string, unknown>;
  analysis?: {
    metrics_dataset?: string;
    gcp_metrics_dataset?: string;
    metric_rows?: Array<Record<string, unknown>>;
    gcp_metric_rows?: Array<Record<string, unknown>>;
  };
  latest_pipeline?: Record<string, unknown> | null;
  workdir?: string;
  current_session_id?: string;
  sessions?: ChatSession[];
  messages?: ChatMessage[];
  local_library?: LocalLibraryResponse;
};

export type LocalLibraryItem = {
  item_id: string;
  name: string;
  category: string;
  data_type: string;
  path: string;
  description?: string;
  tags?: string[];
  region?: string;
  time_range?: string;
  scale?: string;
  crs?: string;
  source?: string;
  license?: string;
  size_bytes?: number;
  size_mb?: number;
  updated_at?: string;
  enabled?: boolean;
  exists?: boolean;
};

export type LocalLibraryResponse = {
  root: string;
  data_dir: string;
  manifest_path: string;
  items: LocalLibraryItem[];
  categories: string[];
  data_types: string[];
  count: number;
  total: number;
  updated_at?: string;
  hint?: string;
};

export type UploadSummary = {
  filename: string;
  type: string;
  size_bytes?: number;
  row_count?: number | null;
  dataset_name?: string;
  status?: string;
  message?: string;
};

const API_BASE = import.meta.env.VITE_API_BASE || '';
function authHeaders(): Record<string, string> {
  return {};
}

export function formatApiError(status: number, statusText: string, detail: unknown): Error {
  const detailText = typeof detail === 'string'
    ? detail.trim()
    : detail && typeof detail === 'object' && 'message' in detail
      ? String((detail as { message?: unknown }).message || '').trim()
      : '';
  if (status === 401) {
    return new Error(`登录已过期，请重新登录后再试。${detailText ? ` ${detailText}` : ''}`.trim());
  }
  if (status === 403) {
    return new Error(detailText || '没有权限执行该操作。');
  }
  return new Error(detailText || `${status} ${statusText}`);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init.headers || {})
    }
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = data.detail || data.error || detail;
    } catch {}
    throw formatApiError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

async function multipart<T>(path: string, data: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: data, headers: authHeaders(), credentials: 'include' });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const payload = await res.json();
      detail = payload.detail || payload.error || detail;
    } catch {}
    throw formatApiError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

async function downloadWithAuth(url: string, fallbackName = 'download') {
  const res = await fetch(`${API_BASE}${url}`, { headers: authHeaders(), credentials: 'include' });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const payload = await res.json();
      detail = payload.detail || payload.error || detail;
    } catch {}
    throw formatApiError(res.status, res.statusText, detail);
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const name = decodeURIComponent(match?.[1] || fallbackName);
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

function downloadNativeFile(url: string, fallbackName = 'download') {
  const anchor = document.createElement('a');
  anchor.href = `${API_BASE}${url}`;
  anchor.download = fallbackName;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export const api = {
  async status() {
    return request<{ ok: boolean; service: string; version: string; profile: string }>('/api/status');
  },
  async tiandituConfig() {
    return request<TiandituConfig>('/api/tianditu/config');
  },
  async mapStations(user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return request<StationCollection>(`/api/map/stations${suffix}`);
  },
  async mapLayers(user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return request<{ layers: ResultMapLayer[]; diagnostics?: Array<Record<string, unknown>> }>(`/api/map/layers${suffix}`);
  },
  async refreshMapLayer(payload: { user_id?: string; session_id?: string; artifact_id?: string; dataset_name?: string }) {
    return request<{ map_ready: boolean; artifact_id?: string; dataset_name?: string; map_layer_id?: string; layer?: ResultMapLayer }>('/api/map/layers/refresh', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  },
  async login(email: string, password: string) {
    return request<AuthSession>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });
  },
  async register(email: string, password: string) {
    return request<AuthSession>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });
  },
  async validate(session_id: string, session_token: string) {
    return request<{ user: CommercialUser }>('/api/auth/validate', {
      method: 'POST',
      body: JSON.stringify({ session_id, session_token })
    });
  },
  async me() {
    return request<CurrentAuthSession>('/api/auth/me');
  },
  async logout() {
    return request<{ ok: boolean }>('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify({})
    });
  },
  async messages(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ messages: ChatMessage[] }>(`/api/chat/messages${q}`);
  },
  async chatSessions(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>(`/api/chat/sessions${q}`);
  },
  async chatModels(user_id: string, session_id: string) {
    const q = `?user_id=${encodeURIComponent(user_id || '')}&session_id=${encodeURIComponent(session_id || '')}`;
    return request<ChatModelState>(`/api/chat/models${q}`);
  },
  async selectChatModel(model: string, user_id: string, session_id: string) {
    return request<ChatModelState>('/api/chat/models/select', {
      method: 'POST',
      body: JSON.stringify({ model, user_id: user_id || '', session_id })
    });
  },
  async createChatSession(user_id?: string, title?: string) {
    return request<{ session_id: string; sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', title: title || '' })
    });
  },
  async switchChatSession(session_id: string, user_id?: string) {
    return request<{ sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>('/api/chat/sessions/switch', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id })
    });
  },
  async deleteChatSession(session_id: string, user_id?: string) {
    return request<{ sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>('/api/chat/sessions/delete', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id })
    });
  },
  async clearChatSession(session_id: string, user_id?: string) {
    return request<{ sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>('/api/chat/sessions/clear', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id })
    });
  },
  async renameChatSession(session_id: string, title: string, user_id?: string) {
    return request<{ sessions: ChatSession[]; current_session_id: string }>('/api/chat/sessions/rename', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id, title })
    });
  },
  async ask(prompt: string, user_id?: string, session_id?: string, frontend_context?: ChatContextPayload, signal?: AbortSignal, task_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; messages?: ChatMessage[]; sessions?: ChatSession[]; current_session_id?: string; task_outcome?: Record<string, unknown>; result_panel?: ResultPanel }>('/api/chat/ask', {
      method: 'POST',
      signal,
      body: JSON.stringify({ prompt, user_id: user_id || '', session_id: session_id || '', task_id: task_id || '', frontend_context: frontend_context || {} })
    });
  },
  async cancelChatTask(task_id: string, user_id?: string, reason?: string) {
    return request<{ ok: boolean; status: string; task_id?: string; message?: string }>('/api/chat/cancel', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', task_id, reason: reason || '用户取消任务。' })
    });
  },
  async deleteArtifact(artifact_id: string, user_id?: string, delete_file = true, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    q.set('delete_file', delete_file ? 'true' : 'false');
    return request<{ ok: boolean; artifact_id: string; filename?: string; status: string; file_deleted: boolean }>(
      `/api/artifacts/${encodeURIComponent(artifact_id)}?${q.toString()}`,
      { method: 'DELETE' }
    );
  },
  async deleteArtifactsBatch(artifact_ids: string[], user_id?: string, delete_file = true, session_id?: string) {
    return request<{ ok: boolean; deleted_count: number; failed_count: number; results: Array<{ ok: boolean; artifact_id: string; filename?: string; status: string; file_deleted: boolean; error?: string }> }>(
      '/api/artifacts/delete-batch',
      {
        method: 'POST',
        body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', artifact_ids, delete_file })
      }
    );
  },
  async retryMessage(message_id: number, content: string, user_id?: string, session_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; messages: ChatMessage[]; sessions: ChatSession[]; current_session_id: string }>('/api/chat/retry', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', message_id, content })
    });
  },
  async uploadFiles(files: FileList | File[], user_id?: string, session_id?: string) {
    const fd = new FormData();
    fd.append('user_id', user_id || '');
    fd.append('session_id', session_id || '');
    Array.from(files).forEach((file) => fd.append('files', file));
    return multipart<{ ok: boolean; count: number; messages: string[]; dashboard: WorkspaceDashboard; upload_summaries?: UploadSummary[]; task_outcome?: Record<string, unknown>; outcome_markdown?: string }>('/api/files/upload', fd);
  },
  async dashboard(user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return request<WorkspaceDashboard>(`/api/workspace/dashboard${suffix}`);
  },
  async workspaceMentions(user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return request<{ items: WorkspaceMention[]; count: number }>(`/api/workspace/mentions${suffix}`);
  },
  async exportWorkspace(user_id?: string, mode: 'latest' | 'all' = 'all', session_id?: string) {
    return request<{ zip_path: string; download_url?: string; file_count: number }>('/api/workspace/export', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', mode })
    });
  },
  async runSoilMoistureWorkflow(user_id?: string, session_id?: string) {
    return request<{ reply: string; model?: string; reason?: string }>('/api/workflows/shandian-soil-moisture', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', run_now: true })
    });
  },
  async localLibrary(params: { query?: string; category?: string; data_type?: string; include_disabled?: boolean } = {}) {
    const sp = new URLSearchParams();
    if (params.query) sp.set('query', params.query);
    if (params.category) sp.set('category', params.category);
    if (params.data_type) sp.set('data_type', params.data_type);
    if (params.include_disabled) sp.set('include_disabled', 'true');
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<LocalLibraryResponse>(`/api/local-library${q}`);
  },
  async rescanLocalLibrary() {
    return request<{ ok: boolean; root: string; added: number; updated: number; total: number }>('/api/local-library/rescan', {
      method: 'POST',
      body: JSON.stringify({})
    });
  },
  async importLocalLibrary(item_ids: string[], user_id?: string, session_id?: string) {
    return request<{ ok: boolean; count: number; messages: string[]; dashboard: WorkspaceDashboard; task_outcome?: Record<string, unknown>; outcome_markdown?: string }>('/api/local-library/import', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', item_ids })
    });
  },
  async pay(user_id: string, plan: PaidPlan) {
    return request<{ user: CommercialUser; order?: unknown; payment?: unknown }>('/api/payments/simulate', {
      method: 'POST',
      body: JSON.stringify({ user_id, plan })
    });
  },
  async submitDownload(input: {
    user_id: string;
    source_key: string;
    resource_type: string;
    region?: string;
    start_date?: string;
    end_date?: string;
    account_mode: 'own' | 'platform' | 'auto';
    request_text?: string;
    output_name?: string;
    session_id?: string;
  }) {
    return request<{ job: unknown; auto_supported?: boolean; auto_started?: boolean; reason?: string; auto_tile_job?: unknown; scene_job?: unknown }>('/api/downloads/submit', {
      method: 'POST',
      body: JSON.stringify(input)
    });
  },
  async preflightDownload(input: {
    user_id: string;
    source_key: string;
    resource_type: string;
    region?: string;
    start_date?: string;
    end_date?: string;
    account_mode: 'own' | 'platform' | 'auto';
    request_text?: string;
    max_pages?: number;
  }) {
    return request<{
      ok: boolean;
      state: string;
      product_key?: string;
      message?: string;
      pages_scanned?: number;
      candidate_count?: number;
      download_selector_hits?: string[];
      scene?: Record<string, unknown>;
      login_health?: Record<string, unknown>;
      region_resolution?: Record<string, unknown>;
    }>('/api/downloads/preflight', {
      method: 'POST',
      body: JSON.stringify(input)
    });
  },
  async jobs(user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return request<{ jobs: DownloadJob[] }>(`/api/downloads/jobs${suffix}`);
  },
  async loginHealth(user_id: string, source_key = 'gscloud', account_mode: 'own' | 'platform' | 'auto' = 'platform') {
    const q = `?user_id=${encodeURIComponent(user_id)}&source_key=${encodeURIComponent(source_key)}&account_mode=${encodeURIComponent(account_mode)}`;
    return request<LoginHealthResponse>(`/api/downloads/login-health${q}`);
  },
  async gscloudStatus() {
    return request<DataSourceAccountStatus>('/api/data-sources/gscloud/status');
  },
  async startGSCloudLogin(timeout_seconds = 300) {
    return request<{ provider: string; login_session_id: string; state: string; user_message: string; poll_interval_ms: number }>('/api/data-sources/gscloud/login/start', {
      method: 'POST',
      body: JSON.stringify({ timeout_seconds })
    });
  },
  async completeGSCloudLogin(login_session_id: string) {
    return request<DataSourceAccountStatus & { login_session_id: string }>('/api/data-sources/gscloud/login/complete', {
      method: 'POST',
      body: JSON.stringify({ login_session_id })
    });
  },
  async logoutGSCloud() {
    return request<DataSourceAccountStatus>('/api/data-sources/gscloud/logout', { method: 'DELETE' });
  },
  async resumeDownloadJob(job_id: string) {
    return request<{ job: DownloadJob; auto_supported?: boolean; auto_started?: boolean; reason?: string; action_required?: ChatActionRequired }>(`/api/download-jobs/${encodeURIComponent(job_id)}/resume`, {
      method: 'POST',
      body: JSON.stringify({})
    });
  },
  async downloadJobLog(user_id: string, job_id: string) {
    const q = `?user_id=${encodeURIComponent(user_id)}&job_id=${encodeURIComponent(job_id)}`;
    return request<{ job: DownloadJob; scene_jobs: Array<Record<string, unknown>>; tile_jobs: Array<Record<string, unknown>>; audit_events: Array<Record<string, unknown>> }>(`/api/downloads/jobs/log${q}`);
  },
  async downloadJobLogFile(user_id: string, job_id: string) {
    const q = `?user_id=${encodeURIComponent(user_id)}&job_id=${encodeURIComponent(job_id)}`;
    return downloadWithAuth(`/api/downloads/jobs/log-download${q}`, `${job_id}_log.txt`);
  },
  async deleteDownloadJob(job_id: string, user_id?: string, session_id?: string) {
    return request<{ ok: boolean; deleted_job_id: string; jobs: DownloadJob[] }>('/api/downloads/jobs/delete', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', job_id })
    });
  },
  async cancelDownloadJob(job_id: string, user_id?: string, reason?: string, session_id?: string) {
    return request<DownloadJob & { jobs: DownloadJob[] }>('/api/downloads/jobs/cancel', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', job_id, reason: reason || '用户取消任务。' })
    });
  },
  async retryDownloadJob(job_id: string, user_id?: string, session_id?: string) {
    return request<{ job: DownloadJob; jobs: DownloadJob[]; auto_supported?: boolean; auto_started?: boolean; reason?: string }>('/api/downloads/jobs/retry', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', job_id })
    });
  },
  async downloadAuthenticated(url: string, fallbackName?: string) {
    return downloadWithAuth(url, fallbackName);
  },
  downloadNative(url: string, fallbackName?: string) {
    return downloadNativeFile(url, fallbackName);
  }
};
