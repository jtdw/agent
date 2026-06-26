import type { LayerVisibility, ResultLayerPaletteName } from './mapLayerPolicy';
import type { MapCommandType } from './mapCommands';

export type ParsedMapTextCommand =
  | { kind: 'map'; command: MapCommandType; reply: string }
  | { kind: 'layer'; layer: keyof LayerVisibility; visible: boolean; reply: string }
  | { kind: 'style'; target: keyof LayerVisibility | 'all'; palette?: ResultLayerPaletteName; reply: string }
  | { kind: 'draw'; action: 'clear' | 'start' | 'stop'; reply: string };

function hasAny(text: string, values: string[]) {
  return values.some((value) => text.includes(value));
}

function paletteFromText(text: string): { name: ResultLayerPaletteName; label: string } | null {
  if (hasAny(text, ['蓝色', '青色', '冷色', 'cyan', 'blue'])) return { name: 'cyan', label: 'Cyan' };
  if (hasAny(text, ['地形色带', '地形配色', 'terrain'])) return { name: 'terrain', label: 'Terrain' };
  if (hasAny(text, ['viridis'])) return { name: 'viridis', label: 'Viridis' };
  if (hasAny(text, ['magma', '岩浆', '暖色'])) return { name: 'magma', label: 'Magma' };
  if (hasAny(text, ['inferno', '火焰'])) return { name: 'inferno', label: 'Inferno' };
  if (hasAny(text, ['plasma', '等离子'])) return { name: 'plasma', label: 'Plasma' };
  if (hasAny(text, ['水分', '湿度', 'moisture'])) return { name: 'moisture', label: 'Moisture' };
  if (hasAny(text, ['彩虹', 'rainbow'])) return { name: 'rainbow', label: 'Rainbow' };
  if (hasAny(text, ['黄橙红', '红黄', 'yellow-orange-red', 'ylorrd'])) return { name: 'yellow-orange-red', label: 'Yellow-Orange-Red' };
  if (hasAny(text, ['蓝绿', 'blue-green', 'bugn'])) return { name: 'blue-green', label: 'Blue-Green' };
  if (hasAny(text, ['紫绿', 'purple-green', 'piyg'])) return { name: 'purple-green', label: 'Purple-Green' };
  if (hasAny(text, ['分类', '定性', 'categorical', 'qualitative'])) return { name: 'categorical', label: 'Categorical' };
  if (hasAny(text, ['灰度', '黑白', 'gray', 'grey'])) return { name: 'grayscale', label: 'Gray' };
  return null;
}

function layerTargetFromText(text: string): keyof LayerVisibility | 'all' | null {
  if (hasAny(text, ['dem', '高程', '地形'])) return 'dem';
  if (hasAny(text, ['站点', '观测'])) return 'stations';
  if (hasAny(text, ['边界', '研究区'])) return 'boundary';
  if (hasAny(text, ['土壤', '水分'])) return 'soil';
  if (hasAny(text, ['全部', '所有', '结果'])) return 'all';
  return null;
}

function targetLabel(target: keyof LayerVisibility | 'all') {
  return target === 'all' ? '结果' : target.toUpperCase();
}

export function parseMapTextCommand(input: string): ParsedMapTextCommand | null {
  const text = input.trim().toLowerCase();
  if (!text) return null;
  if (hasAny(text, ['xgboost', 'xgb', '@{', 'target_col', 'feature_cols', 'spatial_block'])) return null;

  if (hasAny(text, ['配色', '色带', '调色', '换色', '颜色', 'palette', 'color ramp'])) {
    const target = layerTargetFromText(text);
    if (target) {
      const palette = paletteFromText(text);
      if (palette) {
        return { kind: 'style', target, palette: palette.name, reply: `已将 ${targetLabel(target)} 图层配色切换为 ${palette.label}。` };
      }
      return { kind: 'style', target, reply: `已为 ${targetLabel(target)} 图层随机切换配色。` };
    }
  }

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
