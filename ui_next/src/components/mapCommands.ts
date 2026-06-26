export type MapCommandType = 'zoomIn' | 'zoomOut' | 'resetBearing' | 'locate' | 'locateLayer' | 'clearDraw';

export type MapCommand = {
  type: MapCommandType;
  id: number;
  layerId?: string;
};
