export type MapCommandType = 'zoomIn' | 'zoomOut' | 'resetBearing' | 'locate' | 'clearDraw';

export type MapCommand = {
  type: MapCommandType;
  id: number;
};
