import type { Feature, FeatureCollection } from 'geojson';

export type DrawTool = 'point' | 'line' | 'polygon';
export type DrawPoint = [number, number];

const earthRadiusM = 6371008.8;

function toRad(value: number) {
  return value * Math.PI / 180;
}

export function distanceMeters(a: DrawPoint, b: DrawPoint) {
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusM * Math.asin(Math.sqrt(h));
}

export function lineLengthMeters(points: DrawPoint[]) {
  return points.slice(1).reduce((sum, point, index) => sum + distanceMeters(points[index], point), 0);
}

export function polygonAreaSquareMeters(points: DrawPoint[]) {
  if (points.length < 3) return 0;
  const closed = [...points, points[0]];
  let area = 0;
  for (let i = 0; i < closed.length - 1; i += 1) {
    const [lon1, lat1] = closed[i].map(toRad) as DrawPoint;
    const [lon2, lat2] = closed[i + 1].map(toRad) as DrawPoint;
    area += (lon2 - lon1) * (2 + Math.sin(lat1) + Math.sin(lat2));
  }
  return Math.abs(area * earthRadiusM * earthRadiusM / 2);
}

export function formatLength(meters: number) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(0)} m`;
}

export function formatArea(squareMeters: number) {
  return squareMeters >= 1000000 ? `${(squareMeters / 1000000).toFixed(2)} km²` : `${squareMeters.toFixed(0)} m²`;
}

export function drawGeoJson(points: DrawPoint[], tool: DrawTool): FeatureCollection {
  const features: Feature[] = points.map((coordinates, index) => ({
    type: 'Feature',
    properties: { kind: 'point', label: String(index + 1) },
    geometry: { type: 'Point', coordinates }
  }));

  if ((tool === 'line' || tool === 'polygon') && points.length >= 2) {
    features.push({
      type: 'Feature',
      properties: { kind: 'line', length_m: lineLengthMeters(points) },
      geometry: { type: 'LineString', coordinates: points }
    });
  }

  if (tool === 'polygon' && points.length >= 3) {
    features.push({
      type: 'Feature',
      properties: { kind: 'polygon', area_m2: polygonAreaSquareMeters(points) },
      geometry: { type: 'Polygon', coordinates: [[...points, points[0]]] }
    });
  }

  return { type: 'FeatureCollection', features };
}

export function measurementLabel(points: DrawPoint[], tool: DrawTool) {
  if (tool === 'line' && points.length >= 2) return `长度 ${formatLength(lineLengthMeters(points))}`;
  if (tool === 'polygon' && points.length >= 3) return `面积 ${formatArea(polygonAreaSquareMeters(points))}`;
  return `已绘制 ${points.length} 个点`;
}
