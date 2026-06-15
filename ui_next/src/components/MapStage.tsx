import 'maplibre-gl/dist/maplibre-gl.css';

import maplibregl, { GeoJSONSource, Map as MapLibreMap, StyleSpecification } from 'maplibre-gl';
import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Download, Layers3, MapPin, MousePointerClick, Ruler, Trash2, Triangle, Undo2 } from 'lucide-react';
import { api, ResultMapLayer, StationCollection, StationPoint, TiandituConfig } from '@/lib/api';
import type { ChatContextPayload } from '@/lib/chatContext';
import { sanitizeFeatureProperties } from '@/lib/chatContext';
import { cn } from '@/lib/cn';
import { getOverlayVisibilityPlan, type LayerOpacity, type LayerVisibility } from './mapLayerPolicy';
import type { MapCommand } from './mapCommands';
import { drawGeoJson, type DrawPoint, type DrawTool, measurementLabel } from './mapGeometry';
type Basemap = 'standard' | 'satellite' | 'terrain' | 'dark';

const fallbackCenter: [number, number] = [116.18, 41.78];
const fallbackBounds: [number, number, number, number] = [115.5, 41.5, 116.5, 42.5];
type MapBounds = [number, number, number, number];

function normalizeMapBounds(value: unknown): MapBounds | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const bounds = value.map((item) => Number(item));
  if (!bounds.every((item) => Number.isFinite(item))) return null;
  const [minx, miny, maxx, maxy] = bounds;
  if (minx >= maxx || miny >= maxy) return null;
  if (minx < -180 || maxx > 180 || miny < -90 || maxy > 90) return null;
  return [minx, miny, maxx, maxy];
}

function mapBoundsPayload(map: MapLibreMap): MapBounds | undefined {
  const bounds = map.getBounds();
  return normalizeMapBounds([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]) || undefined;
}

function mapLayerSignature(layers: ResultMapLayer[]) {
  return JSON.stringify(layers.map((layer) => ({
    id: layer.id,
    name: layer.name,
    type: layer.type,
    kind: layer.kind,
    preview_url: layer.preview_url,
    bounds: layer.bounds,
    geojson: layer.geojson
  })));
}

function fitPaddingForCanvas(map: MapLibreMap) {
  const canvas = map.getCanvas();
  const width = canvas.clientWidth || canvas.offsetWidth || 0;
  const height = canvas.clientHeight || canvas.offsetHeight || 0;
  if (width < 80 || height < 80) return null;
  const horizontal = width < 640 ? Math.max(16, Math.floor(width * 0.06)) : Math.min(180, Math.floor(width * 0.12));
  const vertical = height < 640 ? Math.max(16, Math.floor(height * 0.06)) : Math.min(110, Math.floor(height * 0.12));
  if (horizontal * 2 >= width - 24 || vertical * 2 >= height - 24) return null;
  return { top: vertical, right: horizontal, bottom: vertical, left: horizontal };
}

function safeFitBounds(map: MapLibreMap, rawBounds: unknown, maxZoom: number, duration: number = 900) {
  const bounds = normalizeMapBounds(rawBounds);
  const padding = fitPaddingForCanvas(map);
  if (!bounds || !padding) return false;
  try {
    map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding, maxZoom, duration });
    return true;
  } catch {
    try {
      map.setCenter([(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]);
      map.setZoom(Math.min(maxZoom, Math.max(2, map.getZoom())));
    } catch {
      // Keep the current view when MapLibre cannot safely fit the requested bounds.
    }
    return false;
  }
}

function expandTiandituTemplate(template: string, subdomains: string[]) {
  return (subdomains.length ? subdomains : ['0', '1', '2', '3', '4', '5', '6', '7']).map((s) => template.replace('{s}', s));
}

function buildTiandituStyle(config: TiandituConfig, basemap: Basemap, theme: 'light' | 'dark'): StyleSpecification {
  const templates = config.tile_url_templates || {};
  const subdomains = config.subdomains || [];
  const mode = basemap === 'dark' ? 'standard' : basemap;
  const baseKey = mode === 'satellite' ? 'image' : mode === 'terrain' ? 'terrain' : 'vector';
  const annoKey = mode === 'satellite' ? 'image_annotation' : mode === 'terrain' ? 'terrain_annotation' : 'vector_annotation';
  const baseTiles = expandTiandituTemplate(templates[baseKey], subdomains);
  const annoTiles = expandTiandituTemplate(templates[annoKey], subdomains);
  const isDark = theme === 'dark' || basemap === 'dark';

  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      tdt_base: {
        type: 'raster',
        tiles: baseTiles,
        tileSize: 256,
        attribution: '© 天地图'
      },
      tdt_annotation: {
        type: 'raster',
        tiles: annoTiles,
        tileSize: 256
      }
    },
    layers: [
      {
        id: 'tdt_base',
        type: 'raster',
        source: 'tdt_base',
        paint: isDark
          ? { 'raster-brightness-min': 0.08, 'raster-brightness-max': 0.62, 'raster-saturation': -0.45, 'raster-contrast': 0.15 }
          : { 'raster-brightness-min': 0, 'raster-brightness-max': 1 }
      },
      {
        id: 'tdt_annotation',
        type: 'raster',
        source: 'tdt_annotation',
        paint: isDark
          ? { 'raster-brightness-min': 0.18, 'raster-brightness-max': 0.82, 'raster-saturation': -0.2 }
          : { 'raster-opacity': 0.95 }
      }
    ]
  };
}

function buildFallbackStyle(theme: 'light' | 'dark'): StyleSpecification {
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {},
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': theme === 'dark' ? '#0a0e1a' : '#eaf3ff' } }
    ]
  };
}

function stationColor(station: StationPoint) {
  const value = station.mean_sm ?? null;
  if (value === null) return '#94a3b8';
  if (value < 0.10) return '#f59e0b';
  if (value < 0.18) return '#22D3EE';
  return '#10b981';
}

function stationWidth(station: StationPoint) {
  const value = station.mean_sm ?? 0.12;
  const normalized = Math.max(0.22, Math.min(1, value / 0.30));
  return Math.round(normalized * 100);
}

function escapeHtml(value: string) {
  return String(value || '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] || ch);
}

function stationGeoJson(stations: StationPoint[]) {
  return {
    type: 'FeatureCollection' as const,
    features: stations.map((station) => ({
      type: 'Feature' as const,
      properties: {
        station_id: station.station_id,
        name: station.name || station.station_id,
        mean_sm: station.mean_sm,
        sample_count: station.sample_count,
        elevation_m: station.elevation_m,
        longitude: station.longitude,
        latitude: station.latitude,
        color: stationColor(station),
        width: stationWidth(station)
      },
      geometry: { type: 'Point' as const, coordinates: [station.longitude, station.latitude] }
    }))
  };
}

function stationPopupHtml(station: StationPoint) {
  const lng = Number(station.longitude);
  const lat = Number(station.latitude);
  const mean = station.mean_sm == null ? '--' : Number(station.mean_sm).toFixed(3);
  const name = escapeHtml(String(station.name || station.station_id || 'station'));
  return `
    <div class="font-black text-sm mb-1">${name}</div>
    <div class="text-xs text-slate-500">2019 5 cm mean soil moisture: ${mean} m3/m3</div>
    <div class="text-xs text-slate-500 mt-1">Samples: ${station.sample_count ?? 0}; elevation: ${station.elevation_m ?? '--'} m</div>
    <div class="text-xs text-slate-500 mt-1">Lon/lat: ${lng.toFixed(5)}, ${lat.toFixed(5)}</div>
    <div class="mt-3 h-2 rounded-full bg-slate-200/70 overflow-hidden"><div style="width:${stationWidth(station)}%; background:linear-gradient(90deg,#0B5FF4,#22D3EE,#10b981)" class="h-full rounded-full"></div></div>
  `;
}

function removeStationCircleLayers(map: MapLibreMap) {
  for (const layerId of ['station_points_outer', 'station_points_halo', 'station_points_core']) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  if (map.getSource('station_points')) map.removeSource('station_points');
}

function setStationMarkerVisibility(map: MapLibreMap, visible: boolean, opacity: number) {
  const markers = (((map as unknown as Record<string, unknown>).__stationMarkers || []) as maplibregl.Marker[]);
  for (const marker of markers) {
    const element = marker.getElement();
    element.style.display = visible ? '' : 'none';
    element.style.opacity = String(Math.max(0, Math.min(1, opacity)));
  }
}

function setStationMarkers(map: MapLibreMap, stations: StationPoint[], onChatContextChange?: (patch: Partial<ChatContextPayload>) => void) {
  const state = map as unknown as Record<string, unknown>;
  const previous = ((state.__stationMarkers || []) as maplibregl.Marker[]);
  previous.forEach((marker) => marker.remove());
  state.__stationMarkers = stations.map((station) => {
    const color = stationColor(station);
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'station-dom-marker';
    element.dataset.testid = 'map-station-marker';
    element.title = `${station.name || station.station_id} ${Number(station.longitude).toFixed(5)}, ${Number(station.latitude).toFixed(5)}`;
    element.style.cssText = [
      'width:17px',
      'height:17px',
      'border-radius:999px',
      'border:2px solid #ffffff',
      `background:${color}`,
      `box-shadow:0 0 0 2px ${color}66, 0 2px 7px rgba(15,23,42,.18)`,
      'cursor:pointer',
      'padding:0',
      'pointer-events:auto'
    ].join(';');
    element.addEventListener('click', (event) => {
      event.stopPropagation();
      onChatContextChange?.({
        selected_layer_id: 'station_points',
        selected_feature_id: String(station.station_id || station.id || ''),
        selected_feature_properties: {
          station_id: station.station_id,
          name: station.name,
          mean_sm: station.mean_sm ?? null,
          sample_count: station.sample_count,
          elevation_m: station.elevation_m ?? null,
          longitude: station.longitude,
          latitude: station.latitude
        },
        selected_map_bounds: mapBoundsPayload(map),
        last_visible_panel: 'map',
        user_focus_hint: 'selected station point'
      });
      new maplibregl.Popup({ closeButton: false, offset: 14, className: 'tdt-glass-popup' })
        .setLngLat([station.longitude, station.latitude])
        .setHTML(stationPopupHtml(station))
        .addTo(map);
    });
    return new maplibregl.Marker({ element, anchor: 'center' })
      .setLngLat([station.longitude, station.latitude])
      .addTo(map);
  });
}

function setStationLayer(map: MapLibreMap, stations: StationPoint[], onChatContextChange?: (patch: Partial<ChatContextPayload>) => void) {
  if (map.isStyleLoaded()) removeStationCircleLayers(map);
  setStationMarkers(map, stations, onChatContextChange);
}
function fitToStations(map: MapLibreMap, collection: StationCollection | null) {
  const bounds = collection?.bounds || fallbackBounds;
  if (safeFitBounds(map, bounds, 9.6)) return;
  map.setCenter(collection?.center || fallbackCenter);
  map.setZoom(8.2);
}

function setLayerPaintIfPresent(map: MapLibreMap, layer: string, property: string, value: unknown) {
  if (map.getLayer(layer)) map.setPaintProperty(layer, property, value);
}

function raiseStationLayers(map: MapLibreMap) {
  for (const layerId of ['station_points_outer', 'station_points_halo', 'station_points_core']) {
    if (!map.getLayer(layerId)) continue;
    try {
      map.moveLayer(layerId);
    } catch {
      // Layer order can only be changed after the style is fully restored.
    }
  }
}

function setDrawLayer(map: MapLibreMap, points: DrawPoint[], tool: DrawTool, opacity: number) {
  if (!map.isStyleLoaded()) return;
  const data = drawGeoJson(points, tool);
  const source = map.getSource('draw_features') as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
  } else {
    map.addSource('draw_features', { type: 'geojson', data });
  }
  if (!map.getLayer('draw_polygon')) {
    map.addLayer({ id: 'draw_polygon', type: 'fill', source: 'draw_features', filter: ['==', ['get', 'kind'], 'polygon'], paint: { 'fill-color': '#0B5FF4', 'fill-opacity': 0.14 } });
  }
  if (!map.getLayer('draw_line')) {
    map.addLayer({ id: 'draw_line', type: 'line', source: 'draw_features', filter: ['==', ['get', 'kind'], 'line'], paint: { 'line-color': '#0B5FF4', 'line-width': 3, 'line-dasharray': [1.2, 0.8] } });
  }
  if (!map.getLayer('draw_points')) {
    map.addLayer({ id: 'draw_points', type: 'circle', source: 'draw_features', filter: ['==', ['get', 'kind'], 'point'], paint: { 'circle-radius': 6, 'circle-color': '#22D3EE', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } });
  }
  setLayerPaintIfPresent(map, 'draw_polygon', 'fill-opacity', 0.2 * opacity);
  setLayerPaintIfPresent(map, 'draw_line', 'line-opacity', opacity);
  setLayerPaintIfPresent(map, 'draw_points', 'circle-opacity', opacity);
}

function raiseDrawLayers(map: MapLibreMap) {
  for (const layerId of ['draw_polygon', 'draw_line', 'draw_points']) {
    if (!map.getLayer(layerId)) continue;
    try {
      map.moveLayer(layerId);
    } catch {
      // Layer order can only be changed after the style is fully restored.
    }
  }
}

function setLayerVisibility(map: MapLibreMap, layers: string[], visible: boolean) {
  for (const layer of layers) {
    if (map.getLayer(layer)) {
      map.setLayoutProperty(layer, 'visibility', visible ? 'visible' : 'none');
    }
  }
}

function layerColor(kind: string, index: number) {
  if (kind === 'soil') return '#10b981';
  if (kind === 'dem') return '#38bdf8';
  if (kind === 'boundary') return '#22D3EE';
  return ['#0B5FF4', '#f59e0b', '#fb7185'][index % 3];
}

function hasBoundaryLayer(layers: ResultMapLayer[]) {
  return layers.some((layer) => (layer.kind || 'boundary') === 'boundary');
}

function hasStations(collection: StationCollection | null) {
  return Boolean(collection?.stations?.length);
}

function publishMapDebugState(map: MapLibreMap | null, stationCollection: StationCollection | null, resultLayers: ResultMapLayer[]) {
  if (typeof window === 'undefined') return;
  (window as unknown as Record<string, unknown>).__gisMapDebug = {
    stationCount: stationCollection?.stations?.length || 0,
    resultLayerCount: resultLayers.length,
    boundaryCount: resultLayers.filter((layer) => (layer.kind || 'boundary') === 'boundary').length,
    layers: map
      ? {
          stationMarkers: (((map as unknown as Record<string, unknown>).__stationMarkers || []) as maplibregl.Marker[]).length,
          drawPolygon: Boolean(map.getLayer('draw_polygon'))
        }
      : {}
  };
}

function bindResultQuery(map: MapLibreMap, layerId: string, layer: ResultMapLayer, onChatContextChange?: (patch: Partial<ChatContextPayload>) => void) {
  const key = `__query_${layerId}`;
  if ((map as unknown as Record<string, unknown>)[key]) return;
  map.on('click', layerId, (event) => {
    const feature = event.features?.[0];
    const props = feature?.properties as Record<string, unknown> | undefined;
    onChatContextChange?.({
      active_dataset_id: String(layer.meta?.dataset_name || layer.name || layer.id || ''),
      selected_layer_id: String(layer.id || layerId),
      selected_feature_id: String(props?.id || props?.station_id || props?.name || feature?.id || ''),
      selected_feature_properties: sanitizeFeatureProperties(props || {}),
      selected_map_bounds: mapBoundsPayload(map),
      last_visible_panel: 'map',
      user_focus_hint: `selected map layer ${layer.name || layer.id}`
    });
    const rows = Object.entries(props || {}).filter(([name, value]) => value !== null && value !== undefined && name !== 'kind').slice(0, 6);
    const body = rows.length
      ? rows.map(([name, value]) => `<div class="text-xs text-slate-500 mt-1">${escapeHtml(name)}：${escapeHtml(String(value))}</div>`).join('')
      : '<div class="text-xs text-slate-500 mt-1">该图层暂无可查询属性。</div>';
    new maplibregl.Popup({ closeButton: false, offset: 12, className: 'tdt-glass-popup' })
      .setLngLat(event.lngLat)
      .setHTML(`<div class="font-black text-sm mb-1">${escapeHtml(layer.name || '地图图层')}</div>${body}`)
      .addTo(map);
  });
  map.on('mouseenter', layerId, () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', layerId, () => { map.getCanvas().style.cursor = ''; });
  (map as unknown as Record<string, unknown>)[key] = true;
}

function setResultMapLayers(map: MapLibreMap, layers: ResultMapLayer[], visibility: LayerVisibility, opacity: LayerOpacity, onChatContextChange?: (patch: Partial<ChatContextPayload>) => void) {
  if (!map.isStyleLoaded()) return;
  const activeIds = new Set<string>();
  layers.forEach((layer, index) => {
    const id = `result_${String(layer.id || index).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    activeIds.add(id);
    const kind = (layer.kind || 'boundary') as keyof LayerVisibility;
    const visible = visibility[kind] ?? true;
    const layerOpacity = opacity[(layer.kind || 'boundary') as keyof LayerOpacity] ?? 1;
    const color = layerColor(layer.kind || '', index);

    if (layer.type === 'raster' && layer.preview_url && layer.bounds?.length === 4) {
      const [minx, miny, maxx, maxy] = layer.bounds;
      const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]];
      const source = map.getSource(id) as maplibregl.ImageSource | undefined;
      if (source) source.updateImage({ url: layer.preview_url, coordinates });
      else map.addSource(id, { type: 'image', url: layer.preview_url, coordinates });
      const rasterId = `${id}_raster`;
      if (!map.getLayer(rasterId)) {
        map.addLayer({ id: rasterId, type: 'raster', source: id, paint: { 'raster-opacity': 0.72, 'raster-fade-duration': 240 } });
      }
      setLayerPaintIfPresent(map, rasterId, 'raster-opacity', 0.72 * layerOpacity);
      setLayerVisibility(map, [rasterId], visible);
      bindResultQuery(map, rasterId, layer, onChatContextChange);
      return;
    }

    if (layer.type !== 'vector' || !layer.geojson) return;
    const source = map.getSource(id) as GeoJSONSource | undefined;
    if (source) source.setData(layer.geojson);
    else map.addSource(id, { type: 'geojson', data: layer.geojson });
    const fillId = `${id}_fill`;
    const lineId = `${id}_line`;
    const pointId = `${id}_point`;
    if (!map.getLayer(fillId)) {
      map.addLayer({ id: fillId, type: 'fill', source: id, filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]], paint: { 'fill-color': color, 'fill-opacity': layer.kind === 'boundary' ? 0.08 : 0.22 } });
    }
    if (!map.getLayer(lineId)) {
      map.addLayer({ id: lineId, type: 'line', source: id, filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon']]], paint: { 'line-color': color, 'line-width': layer.kind === 'boundary' ? 2 : 1.35, 'line-opacity': 0.82 } });
    }
    if (!map.getLayer(pointId)) {
      map.addLayer({ id: pointId, type: 'circle', source: id, filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]], paint: { 'circle-radius': 5, 'circle-color': color, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5, 'circle-opacity': 0.9 } });
    }
    setLayerPaintIfPresent(map, fillId, 'fill-opacity', (layer.kind === 'boundary' ? 0.08 : 0.22) * layerOpacity);
    setLayerPaintIfPresent(map, lineId, 'line-opacity', 0.82 * layerOpacity);
    setLayerPaintIfPresent(map, pointId, 'circle-opacity', 0.9 * layerOpacity);
    [fillId, lineId, pointId].forEach((queryLayerId) => bindResultQuery(map, queryLayerId, layer, onChatContextChange));
    setLayerVisibility(map, [fillId, lineId, pointId], visible);
  });

  const previous = ((map as unknown as Record<string, string[]>).__resultSourceIds || []) as string[];
  previous.filter((id) => !activeIds.has(id)).forEach((id) => {
    [`${id}_raster`, `${id}_fill`, `${id}_line`, `${id}_point`].forEach((layerId) => {
      if (map.getLayer(layerId)) map.removeLayer(layerId);
    });
    if (map.getSource(id)) map.removeSource(id);
  });
  (map as unknown as Record<string, string[]>).__resultSourceIds = Array.from(activeIds);
  raiseStationLayers(map);
  raiseDrawLayers(map);
}

function fitToResultLayers(map: MapLibreMap, layers: ResultMapLayer[]) {
  const bounds = layers.map((layer) => layer.bounds).find((b) => b && b.length === 4);
  return safeFitBounds(map, bounds, 11);
}

export function MapStage({
  theme,
  basemap,
  userId = '',
  drawMode,
  setDrawMode,
  layerVisibility,
  layerOpacity,
  mapCommand,
  onChatContextChange
}: {
  theme: 'light' | 'dark';
  basemap: Basemap;
  userId?: string;
  drawMode: boolean;
  setDrawMode: (value: boolean) => void;
  layerVisibility: LayerVisibility;
  layerOpacity: LayerOpacity;
  mapCommand?: MapCommand | null;
  onChatContextChange?: (patch: Partial<ChatContextPayload>) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const hasFitRef = useRef(false);
  const resultLayerSignatureRef = useRef('');
  const [tdtConfig, setTdtConfig] = useState<TiandituConfig | null>();
  const [stationCollection, setStationCollection] = useState<StationCollection | null>(null);
  const [resultLayers, setResultLayers] = useState<ResultMapLayer[]>([]);
  const [stationError, setStationError] = useState('');
  const [mapError, setMapError] = useState('');
  const [drawPoints, setDrawPoints] = useState<DrawPoint[]>([]);
  const [drawTool, setDrawTool] = useState<DrawTool>('polygon');

  const applyOverlayVisibility = (map: MapLibreMap) => {
    const plan = getOverlayVisibilityPlan(layerVisibility);
    setLayerVisibility(map, plan.stations.layers, plan.stations.visible);
    setLayerVisibility(map, plan.boundary.layers, plan.boundary.visible);
    setLayerVisibility(map, plan.draw.layers, plan.draw.visible);
    setStationMarkerVisibility(map, plan.stations.visible, layerOpacity.stations);
  };

  const refreshMapOverlays = (map: MapLibreMap, collection: StationCollection | null, fit: boolean = false) => {
    if (!map.isStyleLoaded()) return;
    try {
      setResultMapLayers(map, resultLayers, layerVisibility, layerOpacity, onChatContextChange);
      setStationLayer(map, collection?.stations || [], onChatContextChange);
      setDrawLayer(map, drawPoints, drawTool, layerOpacity.draw);
      raiseStationLayers(map);
      raiseDrawLayers(map);
      applyOverlayVisibility(map);
      publishMapDebugState(map, collection, resultLayers);
      if (fit) {
        if (!fitToResultLayers(map, resultLayers)) fitToStations(map, collection);
        hasFitRef.current = true;
      }
      setMapError('');
    } catch (err) {
      setMapError(err instanceof Error ? err.message : '地图图层加载失败');
    }
  };

  const refreshMapOverlaysWhenReady = (fit: boolean = false) => {
    const map = mapRef.current;
    if (!map) return;
    const refresh = () => {
      if (!mapRef.current) return;
      refreshMapOverlays(mapRef.current, stationCollection, fit);
      mapRef.current.resize();
    };
    if (map.isStyleLoaded()) {
      refresh();
      return;
    }
    map.once('style.load', refresh);
    map.once('idle', refresh);
  };

  useEffect(() => {
    api.tiandituConfig().then(setTdtConfig).catch(() => setTdtConfig(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.mapStations(userId);
        if (userId && !hasStations(data)) {
          const fallback = await api.mapStations();
          if (!cancelled) {
            setStationCollection(fallback);
            setStationError(fallback.message || data.message || '');
          }
          return;
        }
        if (!cancelled) {
          setStationCollection(data);
          setStationError(data.message || '');
        }
      } catch (err) {
        if (!userId) {
          if (!cancelled) {
            setStationCollection(null);
            setStationError(err instanceof Error ? err.message : 'Station data failed to load');
          }
          return;
        }
        try {
          const fallback = await api.mapStations();
          if (!cancelled) {
            setStationCollection(fallback);
            setStationError(fallback.message || '');
          }
        } catch {
          if (!cancelled) {
            setStationCollection(null);
            setStationError(err instanceof Error ? err.message : 'Station data failed to load');
          }
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.mapLayers(userId);
        let layers = data.layers || [];
        if (userId && !hasBoundaryLayer(layers)) {
          const fallback = await api.mapLayers();
          const fallbackLayers = (fallback.layers || []).filter((layer) => (layer.kind || 'boundary') === 'boundary');
          layers = [...fallbackLayers, ...layers];
        }
        if (!cancelled) {
          const signature = mapLayerSignature(layers);
          if (signature !== resultLayerSignatureRef.current) {
            resultLayerSignatureRef.current = signature;
            setResultLayers(layers);
          }
        }
      } catch {
        if (!userId) {
          if (!cancelled && resultLayerSignatureRef.current !== '[]') {
            resultLayerSignatureRef.current = '[]';
            setResultLayers([]);
          }
          return;
        }
        try {
          const fallback = await api.mapLayers();
          if (!cancelled) {
            const fallbackLayers = (fallback.layers || []).filter((layer) => (layer.kind || 'boundary') === 'boundary');
            const signature = mapLayerSignature(fallbackLayers);
            if (signature !== resultLayerSignatureRef.current) {
              resultLayerSignatureRef.current = signature;
              setResultLayers(fallbackLayers);
            }
          }
        } catch {
          if (!cancelled && resultLayerSignatureRef.current !== '[]') {
            resultLayerSignatureRef.current = '[]';
            setResultLayers([]);
          }
        }
      }
    };
    load();
    const timer = window.setInterval(load, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [userId]);

  const style = useMemo(() => {
    if (tdtConfig?.enabled && tdtConfig.tile_url_templates) return buildTiandituStyle(tdtConfig, basemap, theme);
    return buildFallbackStyle(theme);
  }, [tdtConfig, basemap, theme]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!mapRef.current) {
      let map: MapLibreMap;
      try {
        map = new maplibregl.Map({
          container: containerRef.current,
          style,
          center: stationCollection?.center || fallbackCenter,
          zoom: 8.2,
          minZoom: 2,
          attributionControl: false
        });
      } catch (err) {
        setMapError(err instanceof Error ? err.message : '地图初始化失败');
        return;
      }
      mapRef.current = map;
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-right');

      const forceResize = () => {
        window.requestAnimationFrame(() => map.resize());
        window.setTimeout(() => map.resize(), 80);
        window.setTimeout(() => map.resize(), 350);
      };

      map.on('load', () => {
        forceResize();
        refreshMapOverlays(map, stationCollection, true);
        onChatContextChange?.({ selected_map_bounds: mapBoundsPayload(map), last_visible_panel: 'map' });
      });
      map.on('moveend', () => {
        onChatContextChange?.({ selected_map_bounds: mapBoundsPayload(map), last_visible_panel: 'map' });
      });
      window.addEventListener('resize', forceResize);
      forceResize();

      return () => {
        window.removeEventListener('resize', forceResize);
        map.remove();
        mapRef.current = null;
      };
    }
    const map = mapRef.current;
    map.setStyle(style);
    const restoreOverlays = () => {
      if (!mapRef.current) return;
      refreshMapOverlays(mapRef.current, stationCollection, false);
      mapRef.current.resize();
    };
    map.once('style.load', restoreOverlays);
    map.once('idle', restoreOverlays);
    window.setTimeout(restoreOverlays, 250);
    window.setTimeout(restoreOverlays, 900);
  }, [style]);

  useEffect(() => {
    if (mapRef.current) {
      setStationLayer(mapRef.current, stationCollection?.stations || [], onChatContextChange);
      applyOverlayVisibility(mapRef.current);
      publishMapDebugState(mapRef.current, stationCollection, resultLayers);
    }
    refreshMapOverlaysWhenReady(false);
    if (!mapRef.current) return;
    if (mapRef.current.isStyleLoaded() && stationCollection?.stations?.length && !hasFitRef.current) {
      fitToStations(mapRef.current, stationCollection);
      hasFitRef.current = true;
    }
  }, [stationCollection]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      refreshMapOverlaysWhenReady(false);
      return;
    }
    setResultMapLayers(map, resultLayers, layerVisibility, layerOpacity, onChatContextChange);
    setStationLayer(map, stationCollection?.stations || [], onChatContextChange);
    raiseStationLayers(map);
    raiseDrawLayers(map);
    applyOverlayVisibility(map);
    publishMapDebugState(map, stationCollection, resultLayers);
    if (resultLayers.length && !hasFitRef.current && fitToResultLayers(map, resultLayers)) {
      hasFitRef.current = true;
    }
  }, [resultLayers, layerVisibility, layerOpacity, stationCollection]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      refreshMapOverlaysWhenReady(false);
      return;
    }
    setDrawLayer(map, drawPoints, drawTool, layerOpacity.draw);
    raiseDrawLayers(map);
    applyOverlayVisibility(map);
    publishMapDebugState(map, stationCollection, resultLayers);
  }, [drawPoints, drawTool, layerOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      refreshMapOverlaysWhenReady(false);
      return;
    }
    setStationLayer(map, stationCollection?.stations || [], onChatContextChange);
    setDrawLayer(map, drawPoints, drawTool, layerOpacity.draw);
    raiseStationLayers(map);
    raiseDrawLayers(map);
    applyOverlayVisibility(map);
    setResultMapLayers(map, resultLayers, layerVisibility, layerOpacity, onChatContextChange);
    publishMapDebugState(map, stationCollection, resultLayers);
  }, [layerVisibility, layerOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const handleClick = (event: maplibregl.MapMouseEvent) => {
      if (!drawMode) return;
      setDrawPoints((points) => [...points, [event.lngLat.lng, event.lngLat.lat]]);
    };
    map.on('click', handleClick);
    return () => {
      map.off('click', handleClick);
    };
  }, [drawMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapCommand) return;
    if (mapCommand.type === 'zoomIn') {
      map.zoomIn({ duration: 260 });
      return;
    }
    if (mapCommand.type === 'zoomOut') {
      map.zoomOut({ duration: 260 });
      return;
    }
    if (mapCommand.type === 'resetBearing') {
      map.easeTo({ bearing: 0, pitch: 0, duration: 420 });
      return;
    }
    if (mapCommand.type === 'locate') {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (position) => {
            map.flyTo({
              center: [position.coords.longitude, position.coords.latitude],
              zoom: Math.max(map.getZoom(), 12),
              duration: 800
            });
          },
          () => {
            if (!fitToResultLayers(map, resultLayers)) fitToStations(map, stationCollection);
          },
          { enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 }
        );
      } else if (!fitToResultLayers(map, resultLayers)) {
        fitToStations(map, stationCollection);
      }
      return;
    }
    if (mapCommand.type === 'clearDraw') {
      setDrawPoints([]);
    }
  }, [mapCommand]);

  useEffect(() => {
    if (!containerRef.current || !mapRef.current) return;
    const ro = new ResizeObserver(() => {
      if (resizeTimerRef.current) window.clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = window.setTimeout(() => mapRef.current?.resize(), 50);
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      if (resizeTimerRef.current) window.clearTimeout(resizeTimerRef.current);
    };
  }, []);

  const stationCount = stationCollection?.count || 0;
  const visibleResultLayers = resultLayers.filter((layer) => layerVisibility[(layer.kind || 'boundary') as keyof LayerVisibility] ?? true);
  const drawSummary = measurementLabel(drawPoints, drawTool);

  const exportDrawGeoJson = () => {
    const blob = new Blob([JSON.stringify(drawGeoJson(drawPoints, drawTool), null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `draw-${drawTool}.geojson`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className={cn('map-stage-root fixed inset-0 z-0 overflow-hidden transition-colors duration-500', drawMode && 'cursor-crosshair')}>
      <div ref={containerRef} data-testid="map-stage" className="map-stage-map absolute inset-0 h-full w-full" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_14%_18%,rgba(255,255,255,.08),transparent_24%),radial-gradient(circle_at_76%_22%,rgba(0,212,255,.08),transparent_28%)] dark:bg-[radial-gradient(circle_at_18%_18%,rgba(34,211,238,.08),transparent_24%),radial-gradient(circle_at_76%_22%,rgba(59,130,246,.08),transparent_30%)]" />

      {tdtConfig !== undefined && !tdtConfig?.enabled && (
        <div className="glass-panel no-drag absolute left-1/2 top-16 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-amber-700 dark:text-amber-200">
          <AlertCircle size={16} strokeWidth={1.7} /> 底图服务暂不可用，当前显示本地占位地图。
        </div>
      )}

      {mapError && (
        <div className="glass-panel no-drag absolute left-1/2 top-16 z-20 max-w-[520px] -translate-x-1/2 rounded-[22px] px-4 py-3 text-sm font-semibold text-amber-700 dark:text-amber-200">
          <AlertCircle className="mr-2 inline" size={16} strokeWidth={1.7} /> 地图暂时无法初始化：{mapError}。聊天和数据工具仍可使用。
        </div>
      )}

      {stationError && stationCount === 0 && (
        <div className="glass-panel no-drag absolute left-1/2 top-28 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-amber-700 dark:text-amber-200">
          <AlertCircle size={16} strokeWidth={1.7} /> {stationError}
        </div>
      )}

      <AnimatePresence>
        {drawMode && (
          <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="hidden">
            绘制工具已激活：在地图上点击落点，2 个点形成线，3 个点以上形成面
          </motion.div>
        )}
      </AnimatePresence>

      {drawMode && (
        <div className="glass-panel no-drag absolute left-1/2 top-14 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
          <MousePointerClick size={14} />
          {(['point', 'line', 'polygon'] as DrawTool[]).map((tool) => (
            <button key={tool} onClick={() => { setDrawTool(tool); setDrawPoints([]); }} className={cn('rounded-full px-3 py-1 font-black', drawTool === tool ? 'bg-ocean text-white' : 'bg-white/45 dark:bg-white/10')}>
              {tool === 'point' ? '点' : tool === 'line' ? '线' : '面'}
            </button>
          ))}
          <span className="px-1">{drawSummary}</span>
        </div>
      )}

      <div className="glass-panel no-drag absolute left-[32%] top-[22%] z-20 rounded-full px-3 py-1 text-xs font-bold text-slate-600 dark:text-slate-300 map-label">
        <Layers3 size={13} className="mr-1 inline" /> 天地图 {basemap === 'satellite' ? '影像' : basemap === 'terrain' ? '地形' : basemap === 'dark' ? '暗色' : '矢量'}底图
      </div>

      {visibleResultLayers.length > 0 && (
        <div className="glass-panel no-drag absolute right-4 top-24 z-20 max-w-[260px] rounded-[22px] px-3 py-3 text-xs font-semibold text-slate-600 dark:text-slate-300 lg:right-[390px]">
          <div className="mb-2 flex items-center gap-2 font-black text-slate-800 dark:text-slate-100"><Layers3 size={14} /> 地图结果图层</div>
          <div className="space-y-1.5">
            {visibleResultLayers.slice(0, 5).map((layer, index) => (
              <div key={layer.id} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: layerColor(layer.kind || '', index) }} />
                <span className="truncate">{layer.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {drawMode && (
        <div className="hidden">
          已绘制 {drawPoints.length} 个点
          <button onClick={() => setDrawPoints((points) => points.slice(0, -1))} disabled={!drawPoints.length} className="rounded-full bg-white/45 px-2 py-1 font-black disabled:opacity-40 dark:bg-white/10">撤销</button>
          <button onClick={() => setDrawPoints([])} disabled={!drawPoints.length} className="rounded-full bg-white/45 px-2 py-1 font-black disabled:opacity-40 dark:bg-white/10">清空</button>
        </div>
      )}

      {drawMode && (
        <div className="glass-panel no-drag absolute bottom-[76px] left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
          {drawSummary}
          <button onClick={() => setDrawPoints((points) => points.slice(0, -1))} disabled={!drawPoints.length} className="rounded-full bg-white/45 px-2 py-1 font-black disabled:opacity-40 dark:bg-white/10" title="撤销"><Undo2 size={14} /></button>
          <button onClick={() => setDrawPoints([])} disabled={!drawPoints.length} className="rounded-full bg-white/45 px-2 py-1 font-black disabled:opacity-40 dark:bg-white/10" title="清空"><Trash2 size={14} /></button>
          <button onClick={exportDrawGeoJson} disabled={!drawPoints.length} className="rounded-full bg-white/45 px-2 py-1 font-black disabled:opacity-40 dark:bg-white/10" title="导出 GeoJSON"><Download size={14} /></button>
        </div>
      )}

      <button onClick={() => setDrawMode(!drawMode)} className={cn('glass-button no-drag absolute bottom-5 left-1/2 z-20 -translate-x-1/2 gap-2', drawMode && 'bg-gradient-to-r from-ocean to-cyan-glow text-white shadow-glow')}>
        <Triangle size={16} strokeWidth={1.5} /> {drawMode ? '退出绘制' : '激活绘制工具'}
      </button>
      <div className="glass-panel no-drag absolute bottom-5 left-[calc(50%+115px)] z-20 flex items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
        <Ruler size={14} strokeWidth={1.5} /> 动态比例尺
      </div>
      <div className="glass-panel no-drag absolute bottom-[124px] left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
        <MapPin size={14} strokeWidth={1.5} /> 点击站点可查看均值、样本数、高程与经纬度
      </div>
    </main>
  );
}
