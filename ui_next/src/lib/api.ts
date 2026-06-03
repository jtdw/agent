
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
  meta?: Record<string, unknown>;
};

export type ChatSession = {
  session_id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type AuthSession = {
  user: CommercialUser;
  session_id: string;
  session_token: string;
  expires_at?: string;
};

export type WorkspaceArtifact = {
  name?: string;
  path: string;
  type?: string;
  size?: number;
  updated_at?: string;
  download_url?: string;
};

export type ResultMapLayer = {
  id: string;
  name: string;
  type: 'vector' | 'raster';
  kind: 'dem' | 'boundary' | 'soil' | string;
  bounds?: [number, number, number, number];
  feature_count?: number;
  geojson?: GeoJSON.FeatureCollection;
  preview_url?: string;
  meta?: Record<string, unknown>;
};

export type DownloadJob = {
  job_id: string;
  user_id?: string;
  source_key?: string;
  resource_type?: string;
  region?: string;
  account_mode?: string;
  output_name?: string;
  status?: string;
  progress?: number;
  stage?: string;
  error_message?: string;
  output_path?: string;
  zip_path?: string;
  download_url?: string;
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
  scene_status?: Record<string, unknown>;
  updated_at?: string;
  finished_at?: string;
};

export type WorkspaceDashboard = {
  summary: string;
  datasets: Array<Record<string, unknown>>;
  artifacts: WorkspaceArtifact[];
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

const API_BASE = import.meta.env.VITE_API_BASE || '';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {})
    }
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = data.detail || data.error || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function multipart<T>(path: string, data: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: data });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const payload = await res.json();
      detail = payload.detail || payload.error || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async status() {
    return request<{ ok: boolean; service: string; version: string; profile: string }>('/api/status');
  },
  async tiandituConfig() {
    return request<TiandituConfig>('/api/tianditu/config');
  },
  async mapStations(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<StationCollection>(`/api/map/stations${q}`);
  },
  async mapLayers(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ layers: ResultMapLayer[] }>(`/api/map/layers${q}`);
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
  async messages(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ messages: ChatMessage[] }>(`/api/chat/messages${q}`);
  },
  async chatSessions(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ sessions: ChatSession[]; current_session_id: string; messages: ChatMessage[] }>(`/api/chat/sessions${q}`);
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
  async renameChatSession(session_id: string, title: string, user_id?: string) {
    return request<{ sessions: ChatSession[]; current_session_id: string }>('/api/chat/sessions/rename', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id, title })
    });
  },
  async ask(prompt: string, user_id?: string, session_id?: string) {
    return request<{ reply: string; model?: string; reason?: string }>('/api/chat/ask', {
      method: 'POST',
      body: JSON.stringify({ prompt, user_id: user_id || '', session_id: session_id || '' })
    });
  },
  async retryMessage(message_id: number, content: string, user_id?: string, session_id?: string) {
    return request<{ reply: string; model?: string; reason?: string; messages: ChatMessage[]; sessions: ChatSession[]; current_session_id: string }>('/api/chat/retry', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', session_id: session_id || '', message_id, content })
    });
  },
  async uploadFiles(files: FileList | File[], user_id?: string) {
    const fd = new FormData();
    fd.append('user_id', user_id || '');
    Array.from(files).forEach((file) => fd.append('files', file));
    return multipart<{ ok: boolean; count: number; messages: string[]; dashboard: WorkspaceDashboard }>('/api/files/upload', fd);
  },
  async dashboard(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<WorkspaceDashboard>(`/api/workspace/dashboard${q}`);
  },
  async exportWorkspace(user_id?: string, mode: 'latest' | 'all' = 'all') {
    return request<{ zip_path: string; download_url?: string; file_count: number }>('/api/workspace/export', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', mode })
    });
  },
  async runSoilMoistureWorkflow(user_id?: string) {
    return request<{ reply: string; model?: string; reason?: string }>('/api/workflows/shandian-soil-moisture', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', run_now: true })
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
  async importLocalLibrary(item_ids: string[], user_id?: string) {
    return request<{ ok: boolean; count: number; messages: string[]; dashboard: WorkspaceDashboard }>('/api/local-library/import', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', item_ids })
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
    account_mode: 'own' | 'platform';
    request_text?: string;
    output_name?: string;
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
    account_mode: 'own' | 'platform';
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
  async jobs(user_id?: string) {
    const q = user_id ? `?user_id=${encodeURIComponent(user_id)}` : '';
    return request<{ jobs: DownloadJob[] }>(`/api/downloads/jobs${q}`);
  },
  async deleteDownloadJob(job_id: string, user_id?: string) {
    return request<{ ok: boolean; deleted_job_id: string; jobs: DownloadJob[] }>('/api/downloads/jobs/delete', {
      method: 'POST',
      body: JSON.stringify({ user_id: user_id || '', job_id })
    });
  }
};
