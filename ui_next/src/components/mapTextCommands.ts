import type { LayerVisibility } from './mapLayerPolicy';
import type { MapCommandType } from './mapCommands';

export type ParsedMapTextCommand =
  | { kind: 'map'; command: MapCommandType; reply: string }
  | { kind: 'layer'; layer: keyof LayerVisibility; visible: boolean; reply: string }
  | { kind: 'draw'; action: 'clear' | 'start' | 'stop'; reply: string };

function normalizeCommand(input: string) {
  return input.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[。.!！?？]+$/g, '').trim();
}

function matchesCommand(text: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(text));
}

function layerCommand(text: string, aliases: string[], layer: keyof LayerVisibility, shownReply: string, hiddenReply: string): ParsedMapTextCommand | null {
  const target = aliases.map((alias) => alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const match = text.match(new RegExp(`^(?:请|麻烦)?(?:把|将)?(?:地图上的?)?(显示|打开|开启|隐藏|关闭|关掉)(?:一下)?\\s*(?:${target})\\s*(?:图层|成果)?$`, 'i'));
  if (!match) return null;
  const visible = ['显示', '打开', '开启'].includes(match[1]);
  return { kind: 'layer', layer, visible, reply: visible ? shownReply : hiddenReply };
}

export function parseMapTextCommand(input: string): ParsedMapTextCommand | null {
  const text = normalizeCommand(input);
  if (!text) return null;
  if (matchesCommand(text, [/^(?:请|麻烦)?(?:把|将)?(?:放大地图|地图放大)(?:一点|一级)?$/, /^zoom in$/])) return { kind: 'map', command: 'zoomIn', reply: '已放大地图。' };
  if (matchesCommand(text, [/^(?:请|麻烦)?(?:把|将)?(?:缩小地图|地图缩小)(?:一点|一级)?$/, /^zoom out$/])) return { kind: 'map', command: 'zoomOut', reply: '已缩小地图。' };
  if (matchesCommand(text, [/^(?:请|麻烦)?(?:定位|回到)(?:当前)?(?:研究区|站点区域|可用区域)$/, /^locate$/])) return { kind: 'map', command: 'locate', reply: '已定位到可用区域。' };
  if (matchesCommand(text, [/^(?:请|麻烦)?(?:把|将)?地图?(?:回正|恢复正北|正北朝上)$/, /^(?:重置)?指南针$/])) return { kind: 'map', command: 'resetBearing', reply: '地图已回正。' };

  const parsedLayer = layerCommand(text, ['dem', '高程', '地形'], 'dem', '已显示 DEM 图层。', '已隐藏 DEM 图层。')
    || layerCommand(text, ['站点', '观测'], 'stations', '已显示站点图层。', '已隐藏站点图层。')
    || layerCommand(text, ['边界', '研究区'], 'boundary', '已显示边界图层。', '已隐藏边界图层。')
    || layerCommand(text, ['土壤水分', '土壤', '水分'], 'soil', '已显示土壤水分结果。', '已隐藏土壤水分结果。');
  if (parsedLayer) return parsedLayer;

  if (/^(?:请|麻烦)?(?:清空|清除)(?:全部)?绘制(?:内容)?$/.test(text)) return { kind: 'draw', action: 'clear', reply: '已清空绘制内容。' };
  if (/^(?:请|麻烦)?(?:开始|打开)绘制(?:工具)?$/.test(text)) return { kind: 'draw', action: 'start', reply: '已打开绘制工具。' };
  if (/^(?:请|麻烦)?(?:退出|关闭|停止)绘制(?:工具)?$/.test(text)) return { kind: 'draw', action: 'stop', reply: '已退出绘制工具。' };
  return null;
}
