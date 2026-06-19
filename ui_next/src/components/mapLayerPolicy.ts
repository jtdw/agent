export type LayerVisibility = { dem: boolean; boundary: boolean; stations: boolean; soil: boolean };

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
