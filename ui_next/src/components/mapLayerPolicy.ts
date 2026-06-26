export type LayerVisibility = { dem: boolean; boundary: boolean; stations: boolean; soil: boolean };
export type ResultLayerPaletteName = 'cyan' | 'terrain' | 'viridis' | 'magma' | 'inferno' | 'plasma' | 'moisture' | 'rainbow' | 'yellow-orange-red' | 'blue-green' | 'purple-green' | 'categorical' | 'grayscale';
export type ResultLayerUiState = { visible: boolean; removed: boolean; palette: ResultLayerPaletteName };
export type ResultLayerStateMap = Record<string, ResultLayerUiState>;
export type ResultLayerLike = { id?: string; name?: string; kind?: string; type?: string };
export type ResultLayerPaletteTarget = keyof LayerVisibility | 'all';
export type ResultLayerPalettePreferences = Partial<Record<ResultLayerPaletteTarget, ResultLayerPaletteName>>;

export const RESULT_LAYER_PALETTES: Record<ResultLayerPaletteName, { label: string; colors: string[] }> = {
  cyan: { label: 'Cyan', colors: ['#0f4c81', '#0ea5e9', '#22d3ee', '#a7f3d0'] },
  terrain: { label: 'Terrain', colors: ['#2d5a27', '#8fbf5a', '#f6e27f', '#c77c3a', '#f8fafc'] },
  viridis: { label: 'Viridis', colors: ['#440154', '#31688e', '#35b779', '#fde725'] },
  magma: { label: 'Magma', colors: ['#000004', '#51127c', '#b73779', '#fc8961', '#fcfdbf'] },
  inferno: { label: 'Inferno', colors: ['#000004', '#420a68', '#932667', '#dd513a', '#fca50a', '#fcffa4'] },
  plasma: { label: 'Plasma', colors: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636', '#f0f921'] },
  moisture: { label: 'Moisture', colors: ['#7c2d12', '#f59e0b', '#65a30d', '#10b981', '#0ea5e9'] },
  rainbow: { label: 'Rainbow', colors: ['#2563eb', '#06b6d4', '#22c55e', '#facc15', '#f97316', '#ef4444'] },
  'yellow-orange-red': { label: 'Yellow-Orange-Red', colors: ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#f03b20', '#bd0026'] },
  'blue-green': { label: 'Blue-Green', colors: ['#f7fcfd', '#ccece6', '#66c2a4', '#238b45', '#005824'] },
  'purple-green': { label: 'Purple-Green', colors: ['#762a83', '#af8dc3', '#e7d4e8', '#d9f0d3', '#7fbf7b', '#1b7837'] },
  categorical: { label: 'Categorical', colors: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2'] },
  grayscale: { label: 'Gray', colors: ['#111827', '#64748b', '#cbd5e1', '#f8fafc'] }
};

const paletteOrder: ResultLayerPaletteName[] = ['viridis', 'terrain', 'magma', 'inferno', 'plasma', 'moisture', 'rainbow', 'yellow-orange-red', 'blue-green', 'purple-green', 'categorical', 'cyan', 'grayscale'];

export const STATION_LAYER_IDS: string[] = [];
export const BOUNDARY_LAYER_IDS: string[] = [];
export const DRAW_LAYER_IDS = ['draw_polygon', 'draw_line', 'draw_points'];

export function getDrawLayerVisibility(_visibility: LayerVisibility) {
  return { visible: true, layers: DRAW_LAYER_IDS };
}

export function getOverlayVisibilityPlan(visibility: LayerVisibility) {
  return {
    stations: { visible: visibility.stations, layers: STATION_LAYER_IDS },
    boundary: { visible: visibility.boundary, layers: BOUNDARY_LAYER_IDS },
    draw: getDrawLayerVisibility(visibility)
  };
}

export function isLocalSecureContext(protocol: string, hostname: string) {
  const host = hostname.toLowerCase();
  return protocol === 'https:' || host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

export function resultLayerKey(layer: ResultLayerLike, fallback = '') {
  return String(layer.id || layer.name || fallback || 'result-layer').replace(/[^a-zA-Z0-9_-]/g, '_');
}

export function defaultResultLayerPalette(layer: ResultLayerLike, index = 0): ResultLayerPaletteName {
  const kind = String(layer.kind || '').toLowerCase();
  if (kind === 'dem') return 'terrain';
  if (kind === 'soil') return 'moisture';
  if (kind === 'boundary') return 'cyan';
  return paletteOrder[index % paletteOrder.length];
}

export function resultLayerPalette(name?: string) {
  const key = (name && name in RESULT_LAYER_PALETTES ? name : 'cyan') as ResultLayerPaletteName;
  return RESULT_LAYER_PALETTES[key];
}

export function nextPaletteName(current?: ResultLayerPaletteName, offset = 1): ResultLayerPaletteName {
  const start = Math.max(0, paletteOrder.indexOf(current || 'viridis'));
  return paletteOrder[(start + offset + 1) % paletteOrder.length];
}

export function preferredResultLayerPalette(layer: ResultLayerLike, index = 0, preferences: ResultLayerPalettePreferences = {}): ResultLayerPaletteName {
  const kind = String(layer.kind || '').toLowerCase() as keyof LayerVisibility;
  return preferences[kind] || preferences.all || defaultResultLayerPalette(layer, index);
}

export function mergeResultLayerState(layers: ResultLayerLike[], current: ResultLayerStateMap = {}, preferences: ResultLayerPalettePreferences = {}): ResultLayerStateMap {
  const next: ResultLayerStateMap = { ...current };
  layers.forEach((layer, index) => {
    const key = resultLayerKey(layer, String(index));
    next[key] = {
      visible: current[key]?.visible ?? true,
      removed: current[key]?.removed ?? false,
      palette: current[key]?.palette || preferredResultLayerPalette(layer, index, preferences)
    };
  });
  return next;
}

export function visibleResultLayers<T extends ResultLayerLike>(layers: T[], state: ResultLayerStateMap = {}): T[] {
  return layers.filter((layer, index) => {
    const layerState = state[resultLayerKey(layer, String(index))];
    return !layerState?.removed && (layerState?.visible ?? true);
  });
}

export function isReferenceMapLayer(layer: ResultLayerLike & { meta?: Record<string, unknown> }) {
  const meta = layer.meta || {};
  const text = [
    layer.id,
    layer.name,
    layer.kind,
    meta.source,
    meta.item_id,
    meta.source_path
  ].map((value) => String(value || '').toLowerCase()).join(' ');
  return text.includes('local_library_shandianhe_basin_boundary')
    || (text.includes('source') && text.includes('local_library') && text.includes('shandianhe'));
}
