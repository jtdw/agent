
import type { ChatContextPayload } from './chatContext';
import type { FeatureCollection } from 'geojson';

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

export type ChatActionRequired = {
  type: 'login_required' | 'clarification_required' | 'confirmation_required' | 'manual_action' | string;
  provider?: string;
  action?: string;
  job_id?: string;
  confirmed_action_id?: string;
  confirmation_prompt?: string;
  product_key?: string;
  message?: string;
  options?: Array<{ value: string; label: string; description?: string }>;
  [key: string]: unknown;
};

export type RealtimeChatEvent = {
  schema_version?: string;
  event_id: string;
  version: number;
  kind: 'task_status' | 'task_progress' | 'task_result' | 'model_token' | 'model_complete' | 'warning' | 'error';
  task_id?: string;
  job_id?: string;
  message_id?: string;
  status?: string;
  progress?: number | null;
  phase?: string;
  current_step?: string;
  heartbeat_at?: string;
  started_at?: string;
  elapsed_ms?: number;
  timeout_reason?: string;
  message?: string;
  delta?: string;
  management_view?: DownloadManagementView;
  presentation_result?: PresentationResult;
  task_update?: Record<string, unknown>;
  created_at?: string;
};

export type ChatArtifact = {
  artifact_id: string;
  name?: string;
  title?: string;
  filename?: string;
  description?: string;
  type?: string;
  kind?: string;
  artifact_type?: string;
  mime_type?: string;
  size_bytes?: number;
  size_kb?: number;
  created_at?: string;
  updated_at?: string;
  group?: string;
  priority?: number;
  previewable?: boolean;
  preview_available?: boolean;
  preview?: unknown;
  hidden_by_default?: boolean;
  map_ready?: boolean;
  status?: 'available' | 'missing' | string;
  source?: { tool_name?: string; workflow_id?: string; [key: string]: unknown };
  meta?: Record<string, unknown>;
};

export type ResolvedArtifactMetadata = ChatArtifact & {
  download_url?: string;
};

export type UserFacingResult = {
  schema_version?: string;
  summary?: string;
  key_findings?: string[];
  primary_artifacts?: ChatArtifact[];
  secondary_artifacts?: ChatArtifact[];
  preview_artifacts?: ChatArtifact[];
  grouped_artifacts?: Array<{ group: string; default_expanded?: boolean; artifacts: ChatArtifact[] }>;
  download_bundle?: { all?: ChatArtifact | null; recommended?: ChatArtifact | null } | null;
  metrics?: Record<string, unknown>;
  insights?: string[];
  warnings?: string[];
  next_actions?: string[];
  technical_details?: Record<string, unknown>;
  debug?: Record<string, unknown>;
};

export type PresentationResult = {
  schema_version?: string;
  response_language?: string;
  status?: 'succeeded' | 'failed' | 'running' | 'awaiting_confirmation' | 'blocked' | string;
  concise_summary?: string;
  executed_steps?: Array<{ step_id?: string; tool_name?: string; status?: string }>;
  data_sources?: string[];
  result_highlights?: string[];
  artifact_refs?: Array<{ artifact_id: string; title?: string; type?: string; source_step_id?: string; source_tool?: string }>;
  map_layer_refs?: Array<{ layer_id: string; name?: string; source_step_id?: string; source_tool?: string }>;
  table_refs?: Array<{ table_id: string; title?: string; source_step_id?: string; source_tool?: string }>;
  image_refs?: Array<{ artifact_id: string; title?: string; source_step_id?: string; source_tool?: string }>;
  warnings?: string[];
  error_summary?: string;
  next_action_suggestions?: string[];
  clarification_question?: string;
};

export type ExecutionSummary = {
  schema_version?: string;
  response_language?: string;
  status?: string;
  summary?: string;
  executed_step_count?: number;
  artifact_count?: number;
  map_layer_count?: number;
  table_count?: number;
  image_count?: number;
  warning_count?: number;
  error_summary?: string;
  clarification_question?: string;
  next_action_count?: number;
};

export type CapabilityResourceType = 'knowledge' | 'tool_cards' | 'products' | 'assets';

export type CapabilityResource = {
  knowledge_id?: string;
  tool_name?: string;
  product_id?: string;
  asset_id?: string;
  title?: string;
  display_name_zh?: string;
  name?: string;
  source?: string;
  language?: string;
  tags?: string[];
  applicable_scope?: string[];
  reliability?: string;
  version?: string;
  status?: 'enabled' | 'disabled' | string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type CapabilityListResponse = {
  schema_version: string;
  registry_version: string;
  resource_type: CapabilityResourceType;
  items: CapabilityResource[];
};

export type CapabilitySearchResponse = {
  schema_version: string;
  registry_version: string;
  query: string;
  items: Array<{
    knowledge_chunk_id: string;
    knowledge_id: string;
    knowledge_version?: string;
    title?: string;
    content?: string;
    source?: string;
    source_trust?: string;
    reliability?: string;
    [key: string]: unknown;
  }>;
};

export type DatasetAvailabilityProfile = {
  product_id: string;
  display_name_zh?: string;
  source_product_key?: string;
  source_url?: string;
  temporal_requirement?: string;
  temporal_coverage?: Record<string, unknown>;
  supported_formats?: string[];
  supported_resolutions?: string[];
  verification_method?: string;
  scan_summary?: string;
  warnings?: string[];
  version?: string;
  status?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type DatasetAvailabilityListResponse = {
  schema_version: string;
  items: DatasetAvailabilityProfile[];
};

export type AdminSystemResetMode = 'keep_accounts' | 'full_reset';

export type AdminSystemResetResponse = {
  ok: boolean;
  mode: AdminSystemResetMode;
  deleted?: { files?: number; directories?: number; bytes?: number; errors?: string[] };
  preserved?: { workspace_entries?: string[]; accounts?: number; capability_config?: boolean };
  capability_cleanup?: { private_knowledge_items?: string[]; index_dirs?: string[] };
};

export type StorageCleanupCandidate = {
  candidate_id: string;
  category: string;
  label?: string;
  kind?: string;
  file_count?: number;
  size_bytes?: number;
  safe_to_delete?: boolean;
  reason?: string;
};

export type StorageCleanupScanResponse = {
  schema_version: string;
  candidates: StorageCleanupCandidate[];
  total_candidates: number;
  total_size_bytes: number;
  referenced_path_count?: number;
};

export type StorageCleanupDeleteResponse = {
  ok: boolean;
  schema_version: string;
  deleted: Array<{ candidate_id: string; label?: string; files?: number; bytes?: number }>;
  errors: string[];
  deleted_count: number;
  freed_bytes: number;
};

export type PlatformAccountLoginHealth = {
  ok?: boolean;
  reason?: string;
  action?: string;
  cookie_count?: number;
  gscloud_cookie_count?: number;
  valid_gscloud_cookie_count?: number;
  authenticated_gscloud_cookie_count?: number;
  [key: string]: unknown;
};

export type PlatformAccount = {
  account_id: string;
  source_key: string;
  label?: string;
  username_preview?: string;
  has_password?: boolean;
  has_storage_state?: boolean;
  daily_limit?: number;
  used_today?: number;
  monthly_limit?: number;
  used_month?: number;
  status?: 'active' | 'disabled' | string;
  last_used_at?: string;
  created_at?: string;
  updated_at?: string;
  login_health?: PlatformAccountLoginHealth;
};

export type PlatformAccountListResponse = {
  schema_version: string;
  accounts: PlatformAccount[];
};

export type PlatformLoginJob = {
  login_job_id?: string;
  state?: string;
  message?: string;
  timeout_seconds?: number;
  created_at?: string;
  updated_at?: string;
};

export type UploadSummary = {
  filename: string;
  type?: string;
  size_bytes?: number;
  row_count?: number;
  dataset_name?: string;
  message?: string;
};

export type WorkspaceMention = {
  id: string;
  name: string;
  mention?: string;
  type: string;
  label?: string;
  description?: string;
  filename?: string;
  row_count?: number | null;
  column_count?: number | null;
  crs?: string;
  meta?: Record<string, unknown>;
};

export type ChatModelState = {
  session_id?: string;
  route_mode?: 'auto' | 'manual';
  selected_model?: string;
  active_model?: string;
  models?: Array<{ id: string; capability?: 'text' | 'vision' | string; label?: string; provider?: string; available?: boolean }>;
  available_models?: Array<{ id: string; label?: string; provider?: string; available?: boolean }>;
  provider_health?: Record<string, unknown>;
};

export type ChatMessage = {
  message_id?: number;
  session_id?: string;
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  meta?: Record<string, unknown> & {
    artifacts?: ChatArtifact[];
    presentation_result?: PresentationResult;
    execution_summary?: ExecutionSummary;
    user_facing_result?: UserFacingResult;
    upload_summaries?: UploadSummary[];
    action_required?: ChatActionRequired;
  };
};

export type ChatSession = {
  session_id: string;
  title: string;
  interaction_mode?: 'chat_only' | 'tool_enabled';
  message_count?: number;
  created_at?: string;
  updated_at?: string;
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
  title?: string;
  filename?: string;
  type?: string;
  size?: number;
  updated_at?: string;
  status?: 'available' | 'missing' | string;
};

export type ResultPanelFile = {
  artifact_id?: string;
  label: string;
  name?: string;
  title?: string;
  filename?: string;
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
  geojson?: FeatureCollection;
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
  artifacts?: ChatArtifact[];
  charged?: number;
  quota_reserved?: number;
  retried_from_job_id?: string;
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
  management_view?: DownloadManagementView;
  updated_at?: string;
  finished_at?: string;
};

export type DownloadManagementView = {
  schema_version?: 'download-management-view/v1' | string;
  task_id: string;
  status: string;
  progress?: number;
  display_title?: string;
  source_name?: string;
  artifact_refs?: Array<{ artifact_id: string; title?: string; type?: string }>;
  map_layer_refs?: Array<{ layer_id: string; name?: string }>;
  warnings?: string[];
  error_code?: string;
  error_title?: string;
  user_message?: string;
  available_actions?: Array<'retry' | 'cancel' | 'login_required' | 'view_artifacts' | 'add_to_map' | string>;
  action_state?: Record<string, string>;
  updated_at?: string;
};

export type DiagnosticEventView = {
  schema_version?: 'diagnostic-event-view/v1' | string;
  timestamp?: string;
  phase?: string;
  level?: 'info' | 'warning' | 'error' | string;
  summary?: string;
  error_code?: string;
  next_action?: string;
};

export type DownloadArtifactRef = { artifact_id: string; title?: string; type?: string };

export type DownloadManagementListResponse = {
  management_views?: DownloadManagementView[];
  artifact_refs?: DownloadArtifactRef[];
  available_actions?: string[];
  deprecated_raw_job_api?: boolean;
};

export type DownloadManagementActionResponse = DownloadManagementListResponse & {
  ok?: boolean;
  management_view?: DownloadManagementView;
  auto_supported?: boolean;
  auto_started?: boolean;
  reason?: string;
  action_required?: ChatActionRequired;
};

export type DownloadSubmitResponse = DownloadManagementActionResponse & {
  presentation_result?: PresentationResult;
  execution_summary?: ExecutionSummary;
};

export type DownloadJobLogResponse = {
  management_view?: DownloadManagementView;
  diagnostic_event_views?: {
    scene_jobs?: DiagnosticEventView[];
    tile_jobs?: DiagnosticEventView[];
    audit_events?: DiagnosticEventView[];
  };
  artifact_refs?: DownloadArtifactRef[];
  available_actions?: string[];
  deprecated_raw_job_api?: boolean;
};

export type DownloadDeleteResponse = DownloadManagementListResponse & {
  ok: boolean;
  deleted_job_id: string;
};

export type LoginHealthResponse = {
  source_key: string;
  account_mode: string;
  login_health: {
    ok?: boolean;
    reason?: string;
    action?: string;
    detail?: string;
    [key: string]: unknown;
  };
};

export type DataSourceAccountStatus = {
  provider: string;
  logged_in: boolean;
  account_mode?: string;
  last_checked_at?: string;
  expires_at?: string | null;
  masked_account?: string | null;
  storage_state_exists?: boolean;
  health_status?: string;
  user_message?: string;
  pending?: boolean;
  login_session_id?: string;
  login_state?: string;
  waiting_jobs?: DownloadJob[];
};

export type GSCloudLoginStartResponse = {
  provider: string;
  login_session_id: string;
  state: string;
  user_message?: string;
  poll_interval_ms?: number;
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
  current_session_id?: string;
  sessions?: ChatSession[];
  messages?: ChatMessage[];
  local_library?: LocalLibraryResponse;
};

const EMPTY_WORKSPACE_DASHBOARD: WorkspaceDashboard = {
  summary: '',
  datasets: [],
  artifacts: [],
  activity: [],
  dataset_type_counts: {},
  runtime_status: {},
  capability_groups: {},
  suggestions: []
};

export type LocalLibraryItem = {
  item_id: string;
  name: string;
  category: string;
  data_type: string;
  filename?: string;
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
  items: LocalLibraryItem[];
  categories: string[];
  data_types: string[];
  count: number;
  total: number;
  updated_at?: string;
  hint?: string;
};

const API_BASE = import.meta.env.VITE_API_BASE || '';
function authHeaders(): Record<string, string> {
  return {};
}

function capabilityAdminHeaders(adminToken?: string): Record<string, string> {
  const token = (adminToken || '').trim();
  return token ? { 'x-admin-token': token } : {};
}

export function formatApiError(status: number, statusText: string, detail: unknown): Error {
  const detailText = typeof detail === 'string'
    ? detail.trim()
    : (detail && typeof detail === 'object' && 'message' in detail)
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

export function filenameFromContentDisposition(disposition: string, fallbackName = 'download') {
  const filenameStar = disposition.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i);
  if (filenameStar?.[1]) {
    const raw = filenameStar[1].trim().replace(/^"|"$/g, '');
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw || fallbackName;
    }
  }
  const filename = disposition.match(/filename\s*=\s*"?([^";]+)"?/i);
  const raw = filename?.[1]?.trim() || fallbackName;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
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
  const name = filenameFromContentDisposition(disposition, fallbackName);
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
}

function downloadNativeFile(url: string, fallbackName = 'download') {
  const href = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const anchor = document.createElement('a');
  anchor.href = href;
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
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<StationCollection>(`/api/map/stations${q}`);
  },
  async mapLayers(user_id?: string, session_id?: string) {
    if (!user_id && !session_id) return { layers: [] as ResultMapLayer[] };
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<{ layers: ResultMapLayer[] }>(`/api/map/layers${q}`);
  },
  async refreshMapLayer(payload: { user_id?: string; session_id?: string; artifact_id?: string; dataset_name?: string }) {
    return request<{ artifact_id?: string; dataset_name?: string; map_layer_id: string; map_ready: boolean; layer?: ResultMapLayer }>('/api/map/layers/refresh', {
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
  async chatModels(user_id?: string, session_id?: string) {
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<ChatModelState>(`/api/chat/models${q}`);
  },
  async selectChatModel(model: string, user_id?: string, session_id?: string) {
    return request<ChatModelState>('/api/chat/models/select', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', model })
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
  async setChatInteractionMode(session_id: string, interaction_mode: 'chat_only' | 'tool_enabled', user_id?: string) {
    return request<{ interaction_mode: 'chat_only' | 'tool_enabled'; sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>('/api/chat/sessions/mode', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id, interaction_mode })
    });
  },
  async ask(prompt: string, user_id?: string, session_id?: string, frontend_context?: ChatContextPayload, signal?: AbortSignal, task_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; images?: string[]; artifacts?: ChatArtifact[]; files?: ChatArtifact[]; presentation_result?: PresentationResult; execution_summary?: ExecutionSummary; user_facing_result?: UserFacingResult; messages?: ChatMessage[]; sessions?: ChatSession[]; current_session_id?: string; task_outcome?: Record<string, unknown>; result_panel?: ResultPanel }>('/api/chat/ask', {
      method: 'POST',
      signal,
      body: JSON.stringify({ prompt, user_id: user_id || '', session_id: session_id || '', task_id: task_id || '', frontend_context: frontend_context || {} })
    });
  },
  async streamChat(
    prompt: string,
    user_id: string | undefined,
    session_id: string | undefined,
    frontend_context: ChatContextPayload | undefined,
    handlers: { onEvent: (event: RealtimeChatEvent) => void },
    signal?: AbortSignal,
    task_id?: string,
  ) {
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      credentials: 'include',
      signal,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ prompt, user_id: user_id || '', session_id: session_id || '', task_id: task_id || '', frontend_context: frontend_context || {} })
    });
    if (!response.ok || !response.body) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        detail = payload.detail || payload.error || detail;
      } catch {}
      throw formatApiError(response.status, response.statusText, detail);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const consumeFrame = (frame: string) => {
      const dataLine = frame.split(/\r?\n/).find((line) => line.startsWith('data:'));
      if (!dataLine) return;
      try {
        handlers.onEvent(JSON.parse(dataLine.slice(5).trim()) as RealtimeChatEvent);
      } catch {}
    };
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || '';
      frames.forEach(consumeFrame);
    }
    if (buffer.trim()) consumeFrame(buffer);
  },
  openChatEventStream(user_id: string, session_id: string, after_version = 0) {
    const params = new URLSearchParams({ user_id, session_id, after_version: String(Math.max(0, after_version)) });
    return new EventSource(`${API_BASE}/api/chat/events?${params.toString()}`, { withCredentials: true });
  },
  async replayChatEvents(user_id: string, session_id: string, after_version = 0) {
    const params = new URLSearchParams({ user_id, session_id, after_version: String(Math.max(0, after_version)) });
    return request<{ schema_version: string; events: RealtimeChatEvent[] }>(`/api/chat/events/replay?${params.toString()}`);
  },
  async confirmChatAction(confirmation_id: string, confirmation_prompt: string, user_id?: string, session_id?: string, frontend_context?: ChatContextPayload, signal?: AbortSignal, task_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; images?: string[]; artifacts?: ChatArtifact[]; files?: ChatArtifact[]; presentation_result?: PresentationResult; execution_summary?: ExecutionSummary; user_facing_result?: UserFacingResult; messages?: ChatMessage[]; sessions?: ChatSession[]; current_session_id?: string; task_outcome?: Record<string, unknown>; result_panel?: ResultPanel }>('/api/chat/confirm', {
      method: 'POST',
      signal,
      body: JSON.stringify({ confirmation_id, confirmation_prompt: confirmation_prompt || '', user_id: user_id || '', session_id: session_id || '', task_id: task_id || '', frontend_context: frontend_context || {} })
    });
  },
  async cancelChatTask(task_id: string, user_id?: string, reason?: string) {
    return request<{ ok: boolean; status: string; task_id?: string; message?: string }>('/api/chat/cancel', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', task_id, reason: reason || '用户取消任务' })
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
  async artifactMetadata(artifact_id: string, user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const query = q.toString();
    return request<ResolvedArtifactMetadata>(`/api/artifacts/${encodeURIComponent(artifact_id)}${query ? `?${query}` : ''}`);
  },
  async downloadArtifactById(artifact_id: string, fallbackName = 'download', user_id?: string, session_id?: string) {
    const q = new URLSearchParams();
    if (user_id) q.set('user_id', user_id);
    if (session_id) q.set('session_id', session_id);
    const query = q.toString();
    return downloadWithAuth(`/api/artifacts/${encodeURIComponent(artifact_id)}/download${query ? `?${query}` : ''}`, fallbackName);
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
    if (!user_id && !session_id) return EMPTY_WORKSPACE_DASHBOARD;
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<WorkspaceDashboard>(`/api/workspace/dashboard${q}`);
  },
  async workspaceMentions(user_id?: string, session_id?: string) {
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<{ items: WorkspaceMention[]; count: number }>(`/api/workspace/mentions${q}`);
  },
  async exportWorkspace(user_id?: string, session_id?: string, mode: 'latest' | 'all' = 'all') {
    return request<{ artifact_id: string; download_url?: string; file_count: number; mode?: 'latest' | 'all' | string }>('/api/workspace/export', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', mode })
    });
  },
  async deleteWorkspaceArtifact(input: { user_id?: string; session_id?: string; artifact_id: string }) {
    return request<{ ok: boolean; artifact_id: string; status: string; file_deleted: boolean; deleted_artifacts: string[]; deleted_datasets: string[]; dashboard: WorkspaceDashboard }>('/api/workspace/artifacts/delete', {
      method: 'POST',
      body: JSON.stringify({ user_id: input.user_id || '', session_id: input.session_id || '', artifact_id: input.artifact_id || '' })
    });
  },
  async runSoilMoistureWorkflow(user_id?: string, session_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; messages?: ChatMessage[]; sessions?: ChatSession[]; current_session_id?: string; result_panel?: ResultPanel }>('/api/workflows/shandian-soil-moisture', {
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
    return request<{ ok: boolean; added: number; updated: number; total: number }>('/api/local-library/rescan', {
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
  async capabilityResources(resource_type: CapabilityResourceType, params: { include_disabled?: boolean; admin_token?: string } = {}) {
    const sp = new URLSearchParams();
    if (params.include_disabled) sp.set('include_disabled', 'true');
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<CapabilityListResponse>(`/api/admin/capabilities/${encodeURIComponent(resource_type)}${q}`, {
      headers: capabilityAdminHeaders(params.admin_token)
    });
  },
  async upsertCapabilityKnowledge(payload: CapabilityResource, admin_token?: string) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>('/api/admin/capabilities/knowledge', {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify(payload)
    });
  },
  async uploadCapabilityKnowledge(input: {
    file: File;
    admin_token?: string;
    knowledge_id?: string;
    title?: string;
    source?: string;
    language?: string;
    tags?: string[];
    applicable_scope?: string[];
    reliability?: string;
    version?: string;
    status?: string;
  }) {
    const fd = new FormData();
    fd.append('file', input.file);
    if (input.knowledge_id) fd.append('knowledge_id', input.knowledge_id);
    if (input.title) fd.append('title', input.title);
    if (input.source) fd.append('source', input.source);
    if (input.language) fd.append('language', input.language);
    if (input.tags?.length) fd.append('tags', input.tags.join(','));
    if (input.applicable_scope?.length) fd.append('applicable_scope', input.applicable_scope.join(','));
    if (input.reliability) fd.append('reliability', input.reliability);
    if (input.version) fd.append('version', input.version);
    if (input.status) fd.append('status', input.status);
    const res = await fetch(`${API_BASE}/api/admin/capabilities/knowledge/upload`, {
      method: 'POST',
      credentials: 'include',
      headers: { ...authHeaders(), ...capabilityAdminHeaders(input.admin_token) },
      body: fd
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const payload = await res.json();
        detail = payload.detail || payload.error || detail;
      } catch {}
      throw formatApiError(res.status, res.statusText, detail);
    }
    return res.json() as Promise<{ ok: boolean; item: CapabilityResource; registry_version: string }>;
  },
  async upsertCapabilityToolCard(payload: CapabilityResource, admin_token?: string) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>('/api/admin/capabilities/tool-cards', {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify(payload)
    });
  },
  async upsertCapabilityProduct(payload: CapabilityResource, admin_token?: string) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>('/api/admin/capabilities/products', {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify(payload)
    });
  },
  async upsertCapabilityAsset(payload: CapabilityResource, admin_token?: string) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>('/api/admin/capabilities/assets', {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify(payload)
    });
  },
  async updateCapabilityStatus(
    resource_type: CapabilityResourceType,
    item_id: string,
    status: 'draft' | 'pending_review' | 'active' | 'deprecated' | 'disabled' | 'enabled' | string,
    admin_token?: string,
    options?: { actor?: string; summary?: string }
  ) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>(`/api/admin/capabilities/${encodeURIComponent(resource_type)}/${encodeURIComponent(item_id)}/status`, {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify({ status, actor: options?.actor || 'admin', summary: options?.summary || '' })
    });
  },
  async rollbackCapabilityResource(resource_type: CapabilityResourceType, item_id: string, version: string, admin_token?: string) {
    return request<{ ok: boolean; item: CapabilityResource; registry_version: string }>(`/api/admin/capabilities/${encodeURIComponent(resource_type)}/${encodeURIComponent(item_id)}/rollback`, {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify({ version })
    });
  },
  async testCapabilityKnowledgeSearch(params: { query: string; limit?: number; language?: string; scope?: string; admin_token?: string }) {
    const sp = new URLSearchParams({ query: params.query });
    if (params.limit) sp.set('limit', String(params.limit));
    if (params.language) sp.set('language', params.language);
    if (params.scope) sp.set('scope', params.scope);
    return request<CapabilitySearchResponse>(`/api/admin/capabilities/knowledge/search/test?${sp.toString()}`, {
      headers: capabilityAdminHeaders(params.admin_token)
    });
  },
  async datasetAvailabilityProfiles(params: { include_inactive?: boolean; admin_token?: string } = {}) {
    const sp = new URLSearchParams();
    if (params.include_inactive !== undefined) sp.set('include_inactive', String(Boolean(params.include_inactive)));
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<DatasetAvailabilityListResponse>(`/api/admin/dataset-availability${q}`, {
      headers: capabilityAdminHeaders(params.admin_token)
    });
  },
  async scanDatasetAvailability(product_id: string, input: { scan_method?: string; actor?: string; summary?: string; admin_token?: string } = {}) {
    return request<{ ok: boolean; schema_version: string; item: DatasetAvailabilityProfile }>(`/api/admin/dataset-availability/${encodeURIComponent(product_id)}/scan`, {
      method: 'POST',
      headers: capabilityAdminHeaders(input.admin_token),
      body: JSON.stringify({
        scan_method: input.scan_method || 'catalog_metadata',
        actor: input.actor || 'admin',
        summary: input.summary || ''
      })
    });
  },
  async updateDatasetAvailabilityStatus(product_id: string, status: string, admin_token?: string, options?: { actor?: string; summary?: string }) {
    return request<{ ok: boolean; schema_version: string; item: DatasetAvailabilityProfile }>(`/api/admin/dataset-availability/${encodeURIComponent(product_id)}/status`, {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify({ status, actor: options?.actor || 'admin', summary: options?.summary || '' })
    });
  },
  async systemReset(input: { mode: AdminSystemResetMode; confirm_text: string; admin_token?: string }) {
    return request<AdminSystemResetResponse>('/api/admin/system-reset', {
      method: 'POST',
      headers: capabilityAdminHeaders(input.admin_token),
      body: JSON.stringify({ mode: input.mode, confirm_text: input.confirm_text })
    });
  },
  async storageCleanupScan(admin_token?: string) {
    return request<StorageCleanupScanResponse>('/api/admin/storage-cleanup/scan', {
      headers: capabilityAdminHeaders(admin_token)
    });
  },
  async storageCleanupDelete(input: { candidate_ids: string[]; confirm_text: string; admin_token?: string }) {
    return request<StorageCleanupDeleteResponse>('/api/admin/storage-cleanup/delete', {
      method: 'POST',
      headers: capabilityAdminHeaders(input.admin_token),
      body: JSON.stringify({ candidate_ids: input.candidate_ids, confirm_text: input.confirm_text })
    });
  },
  async adminPlatformAccounts(params: { source_key?: string; include_inactive?: boolean; admin_token?: string } = {}) {
    const sp = new URLSearchParams();
    if (params.source_key) sp.set('source_key', params.source_key);
    if (params.include_inactive !== undefined) sp.set('include_inactive', String(Boolean(params.include_inactive)));
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<PlatformAccountListResponse>(`/api/admin/platform-accounts${q}`, {
      headers: capabilityAdminHeaders(params.admin_token)
    });
  },
  async upsertAdminPlatformAccount(input: {
    source_key?: string;
    username?: string;
    password?: string;
    label?: string;
    daily_limit?: number;
    monthly_limit?: number;
    admin_token?: string;
  }) {
    return request<{ ok: boolean; account: PlatformAccount }>('/api/admin/platform-accounts', {
      method: 'POST',
      headers: capabilityAdminHeaders(input.admin_token),
      body: JSON.stringify({
        source_key: input.source_key || 'gscloud',
        username: input.username || '',
        password: input.password || '',
        label: input.label || '',
        daily_limit: input.daily_limit ?? 50,
        monthly_limit: input.monthly_limit ?? 1000
      })
    });
  },
  async startAdminPlatformAccountLogin(account_id: string, input: { timeout_seconds?: number; headless?: boolean; admin_token?: string } = {}) {
    return request<{ ok: boolean; login_job: PlatformLoginJob; account: PlatformAccount }>(`/api/admin/platform-accounts/${encodeURIComponent(account_id)}/login`, {
      method: 'POST',
      headers: capabilityAdminHeaders(input.admin_token),
      body: JSON.stringify({ timeout_seconds: input.timeout_seconds ?? 300, headless: Boolean(input.headless) })
    });
  },
  async adminPlatformAccountHealth(account_id: string, admin_token?: string) {
    return request<{ ok: boolean; account_id: string; login_health: PlatformAccountLoginHealth }>(`/api/admin/platform-accounts/${encodeURIComponent(account_id)}/health`, {
      headers: capabilityAdminHeaders(admin_token)
    });
  },
  async updateAdminPlatformAccountStatus(account_id: string, status: 'active' | 'disabled', admin_token?: string) {
    return request<{ ok: boolean; account: PlatformAccount }>(`/api/admin/platform-accounts/${encodeURIComponent(account_id)}/status`, {
      method: 'POST',
      headers: capabilityAdminHeaders(admin_token),
      body: JSON.stringify({ status })
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
    include_raw?: boolean;
  }) {
    return request<DownloadSubmitResponse>('/api/downloads/submit', {
      method: 'POST',
      body: JSON.stringify(input)
    });
  },
  async preflightDownload(input: {
    user_id: string;
    session_id?: string;
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
    const sp = new URLSearchParams();
    if (user_id) sp.set('user_id', user_id);
    if (session_id) sp.set('session_id', session_id);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return request<DownloadManagementListResponse>(`/api/downloads/jobs${q}`);
  },
  async loginHealth(user_id: string, source_key = 'gscloud', account_mode: 'own' | 'platform' | 'auto' = 'platform') {
    const q = `?user_id=${encodeURIComponent(user_id)}&source_key=${encodeURIComponent(source_key)}&account_mode=${encodeURIComponent(account_mode)}`;
    return request<LoginHealthResponse>(`/api/downloads/login-health${q}`);
  },
  async gscloudStatus() {
    return request<DataSourceAccountStatus>('/api/data-sources/gscloud/status');
  },
  async startGSCloudLogin(timeout_seconds = 300) {
    return request<GSCloudLoginStartResponse>('/api/data-sources/gscloud/login/start', {
      method: 'POST',
      body: JSON.stringify({ timeout_seconds })
    });
  },
  async completeGSCloudLogin(login_session_id: string) {
    return request<DataSourceAccountStatus>('/api/data-sources/gscloud/login/complete', {
      method: 'POST',
      body: JSON.stringify({ login_session_id })
    });
  },
  async logoutGSCloud() {
    return request<DataSourceAccountStatus>('/api/data-sources/gscloud/logout', {
      method: 'DELETE',
      body: JSON.stringify({})
    });
  },
  async resumeDownloadJob(job_id: string) {
    return request<DownloadManagementActionResponse>(`/api/download-jobs/${encodeURIComponent(job_id)}/resume`, {
      method: 'POST',
      body: JSON.stringify({})
    });
  },
  async downloadJobLog(user_id: string, job_id: string, session_id?: string) {
    const sp = new URLSearchParams({ user_id, job_id });
    if (session_id) sp.set('session_id', session_id);
    const q = `?${sp.toString()}`;
    return request<DownloadJobLogResponse>(`/api/downloads/jobs/log${q}`);
  },
  async downloadJobLogFile(user_id: string, job_id: string, session_id?: string) {
    const sp = new URLSearchParams({ user_id, job_id });
    if (session_id) sp.set('session_id', session_id);
    const q = `?${sp.toString()}`;
    return downloadWithAuth(`/api/downloads/jobs/log-download${q}`, `${job_id}_log.txt`);
  },
  async deleteDownloadJob(job_id: string, user_id?: string, session_id?: string) {
    return request<DownloadDeleteResponse>('/api/downloads/jobs/delete', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', job_id })
    });
  },
  async cancelDownloadJob(job_id: string, user_id?: string, reason?: string, session_id?: string) {
    return request<DownloadManagementActionResponse>('/api/downloads/jobs/cancel', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', job_id, reason: reason || '用户取消任务。' })
    });
  },
  async retryDownloadJob(job_id: string, user_id?: string, session_id?: string) {
    return request<DownloadManagementActionResponse>('/api/downloads/jobs/retry', {
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
