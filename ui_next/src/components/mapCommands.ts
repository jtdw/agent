export type MapCommandType = 'zoomIn' | 'zoomOut' | 'resetBearing' | 'locate' | 'clearDraw' | 'fitLayer';

export type MapCommand = {
  type: MapCommandType;
  id: number;
  layerId?: string;
};
