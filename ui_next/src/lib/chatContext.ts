export type MapBounds = [number, number, number, number];

export type ChatContextPayload = {
  session_id?: string;
  active_dataset_id?: string;
  selected_artifact_id?: string;
  selected_artifact_type?: string;
  selected_artifact_path?: string;
  selected_layer_id?: string;
  selected_feature_id?: string;
  selected_feature_properties?: Record<string, string | number | boolean | null>;
  selected_map_bounds?: MapBounds;
  selected_model_result_id?: string;
  active_task_id?: string;
  last_visible_panel?: string;
  user_focus_hint?: string;
};

const allowedKeys = new Set([
  'session_id',
  'active_dataset_id',
  'selected_artifact_id',
  'selected_artifact_type',
  'selected_artifact_path',
  'selected_layer_id',
  'selected_feature_id',
  'selected_feature_properties',
  'selected_map_bounds',
  'selected_model_result_id',
  'active_task_id',
  'last_visible_panel',
  'user_focus_hint'
]);
const blockedKeyParts = ['file', 'content', 'blob', 'base64', 'raw', 'text', 'html', 'password', 'token', 'secret', 'cookie'];
const sensitiveValuePattern = /(password|token|secret|cookie|authorization|api[_-]?key)\s*[:=]/i;

function cleanString(value: unknown, max = 200) {
  return String(value || '').trim().slice(0, max);
}

function blockedKey(key: string) {
  const lower = key.toLowerCase();
  return blockedKeyParts.some((part) => lower.includes(part));
}

function looksSensitiveValue(value: unknown) {
  const text = String(value || '');
  return sensitiveValuePattern.test(text) || /\bsk-[A-Za-z0-9_-]{8,}/.test(text);
}

function sanitizeArtifactPath(value: unknown) {
  const text = cleanString(value);
  if (!text) return '';
  const lower = text.toLowerCase();
  if (/^[a-zA-Z]:[\\/]/.test(text)) return '';
  if (lower.startsWith('data:') || lower.startsWith('javascript:') || lower.startsWith('file:') || lower.startsWith('http:') || lower.startsWith('https:')) return '';

  let decoded = '';
  try {
    decoded = decodeURIComponent(text).replace(/\\/g, '/');
  } catch {
    decoded = text.replace(/\\/g, '/');
  }
  if (decoded.startsWith('/api/files/artifact?')) {
    const query = decoded.split('?', 2)[1] || '';
    const path = new URLSearchParams(query).get('path') || '';
    return sanitizeArtifactPath(path);
  }
  if (decoded.startsWith('/')) return '';
  if (decoded.split('/').filter(Boolean).includes('..')) return '';
  return text;
}

function scalar(value: unknown): string | number | boolean | null {
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value;
  return cleanString(value);
}

export function sanitizeFeatureProperties(value: unknown): Record<string, string | number | boolean | null> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const props: Record<string, string | number | boolean | null> = {};
  for (const [rawKey, rawValue] of Object.entries(value as Record<string, unknown>)) {
    const key = cleanString(rawKey, 80);
    if (!key || blockedKey(key)) continue;
    if (rawValue && typeof rawValue === 'object') continue;
    props[key] = scalar(rawValue);
    if (Object.keys(props).length >= 12) break;
  }
  while (JSON.stringify(props).length > 4096) {
    const keys = Object.keys(props);
    if (!keys.length) break;
    delete props[keys[keys.length - 1]];
  }
  return props;
}

function sanitizeBounds(value: unknown): MapBounds | undefined {
  if (!Array.isArray(value) || value.length !== 4) return undefined;
  const bounds = value.map((item) => Number(item));
  if (!bounds.every(Number.isFinite)) return undefined;
  const [minx, miny, maxx, maxy] = bounds;
  if (minx >= maxx || miny >= maxy || minx < -180 || maxx > 180 || miny < -90 || maxy > 90) return undefined;
  return [minx, miny, maxx, maxy];
}

export function sanitizeChatContextPayload(input: Partial<ChatContextPayload> | Record<string, unknown> | null | undefined): ChatContextPayload {
  if (!input || typeof input !== 'object') return {};
  const output: ChatContextPayload = {};
  for (const [key, value] of Object.entries(input)) {
    if (!allowedKeys.has(key) || value === undefined || value === null || value === '') continue;
    if (key === 'selected_feature_properties') {
      const props = sanitizeFeatureProperties(value);
      if (Object.keys(props).length) output.selected_feature_properties = props;
    } else if (key === 'selected_map_bounds') {
      const bounds = sanitizeBounds(value);
      if (bounds) output.selected_map_bounds = bounds;
    } else if (key === 'selected_artifact_path') {
      const path = sanitizeArtifactPath(value);
      if (path) output.selected_artifact_path = path;
    } else {
      if (!looksSensitiveValue(value)) (output as Record<string, unknown>)[key] = cleanString(value);
    }
  }
  while (JSON.stringify(output).length > 4096) {
    if (output.selected_feature_properties) delete output.selected_feature_properties;
    else break;
  }
  return output;
}

export function mergeChatContext(current: ChatContextPayload, patch: Partial<ChatContextPayload>): ChatContextPayload {
  return sanitizeChatContextPayload({ ...current, ...patch });
}
