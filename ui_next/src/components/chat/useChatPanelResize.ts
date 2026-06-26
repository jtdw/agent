import { useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';

type UseChatPanelResizeArgs = {
  initialWidth?: number;
  minWidth?: number;
  maxWidth?: number;
};

export function useChatPanelResize({
  initialWidth = 430,
  minWidth = 360,
  maxWidth = 680,
}: UseChatPanelResizeArgs = {}) {
  const [width, setWidth] = useState(initialWidth);
  const panelRef = useRef<HTMLDivElement>(null);

  const dragHandle = useMemo(() => ({
    onPointerDown: (event: PointerEvent) => {
      const startX = event.clientX;
      const startWidth = width;
      const move = (moveEvent: globalThis.PointerEvent) => {
        setWidth(Math.min(maxWidth, Math.max(minWidth, startWidth + moveEvent.clientX - startX)));
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
  }), [maxWidth, minWidth, width]);

  const panelStyle = useMemo<CSSProperties>(() => ({
    width: `min(${width}px, calc(100vw - 1.5rem))`,
    minWidth: `min(${minWidth}px, calc(100vw - 1.5rem))`,
  }), [minWidth, width]);

  return { panelRef, panelStyle, dragHandle };
}
