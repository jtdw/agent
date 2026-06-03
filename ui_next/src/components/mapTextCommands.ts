import type { LayerVisibility } from './mapLayerPolicy';
import type { MapCommandType } from './mapCommands';

export type ParsedMapTextCommand =
  | { kind: 'map'; command: MapCommandType; reply: string }
  | { kind: 'layer'; layer: keyof LayerVisibility; visible: boolean; reply: string }
  | { kind: 'draw'; action: 'clear' | 'start' | 'stop'; reply: string };

function hasAny(text: string, values: string[]) {
  return values.some((value) => text.includes(value));
}

export function parseMapTextCommand(input: string): ParsedMapTextCommand | null {
  const text = input.trim().toLowerCase();
  if (!text) return null;
  if (hasAny(text, ['放大', 'zoom in'])) return { kind: 'map', command: 'zoomIn', reply: '已放大地图。' };
  if (hasAny(text, ['缩小', 'zoom out'])) return { kind: 'map', command: 'zoomOut', reply: '已缩小地图。' };
  if (hasAny(text, ['定位', '回到研究区', '站点区域', 'locate'])) return { kind: 'map', command: 'locate', reply: '已定位到可用区域。' };
  if (hasAny(text, ['指南针', '回正', '正北'])) return { kind: 'map', command: 'resetBearing', reply: '地图已回正。' };

  const visible = hasAny(text, ['显示', '打开', '开启']);
  const hidden = hasAny(text, ['隐藏', '关闭', '关掉']);
  if (visible || hidden) {
    const nextVisible = visible && !hidden;
    if (hasAny(text, ['dem', '高程', '地形'])) return { kind: 'layer', layer: 'dem', visible: nextVisible, reply: nextVisible ? '已显示 DEM 图层。' : '已隐藏 DEM 图层。' };
    if (hasAny(text, ['站点', '观测'])) return { kind: 'layer', layer: 'stations', visible: nextVisible, reply: nextVisible ? '已显示站点图层。' : '已隐藏站点图层。' };
    if (hasAny(text, ['边界', '研究区'])) return { kind: 'layer', layer: 'boundary', visible: nextVisible, reply: nextVisible ? '已显示边界图层。' : '已隐藏边界图层。' };
    if (hasAny(text, ['土壤', '水分'])) return { kind: 'layer', layer: 'soil', visible: nextVisible, reply: nextVisible ? '已显示土壤水分结果。' : '已隐藏土壤水分结果。' };
  }

  if (hasAny(text, ['清空绘制', '清除绘制'])) return { kind: 'draw', action: 'clear', reply: '已清空绘制内容。' };
  if (hasAny(text, ['开始绘制', '打开绘制'])) return { kind: 'draw', action: 'start', reply: '已打开绘制工具。' };
  if (hasAny(text, ['退出绘制', '关闭绘制'])) return { kind: 'draw', action: 'stop', reply: '已退出绘制工具。' };
  return null;
}
