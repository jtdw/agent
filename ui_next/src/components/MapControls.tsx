import { Compass, LocateFixed, Minus, Moon, Plus, Sun, Waypoints } from 'lucide-react';
import { motion } from 'framer-motion';
import type { MapCommandType } from './mapCommands';

export function MapControls({
  theme,
  toggleTheme,
  drawMode,
  toggleDrawMode,
  onMapCommand
}: {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  drawMode: boolean;
  toggleDrawMode: () => void;
  onMapCommand: (command: MapCommandType) => void;
}) {
  const buttons = [
    { icon: Plus, label: '放大', onClick: () => onMapCommand('zoomIn') },
    { icon: Minus, label: '缩小', onClick: () => onMapCommand('zoomOut') },
    { icon: Compass, label: '回正方向', onClick: () => onMapCommand('resetBearing') },
    { icon: LocateFixed, label: '定位', onClick: () => onMapCommand('locate') },
    { icon: Waypoints, label: drawMode ? '退出绘制' : '绘制', onClick: toggleDrawMode, active: drawMode }
  ];

  return (
    <div className="no-drag fixed bottom-24 right-5 z-40 flex flex-col gap-3">
      {buttons.map(({ icon: Icon, label, onClick, active }) => (
        <motion.button
          key={label}
          onClick={onClick}
          whileHover={{ scale: 1.08, y: -1 }}
          whileTap={{ scale: 0.97 }}
          title={label}
          className={active ? 'grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow ring-1 ring-white/60' : 'glass-panel grid h-12 w-12 place-items-center rounded-2xl text-slate-700 transition hover:text-ocean dark:text-slate-200 dark:hover:text-cyan-glow'}
        >
          <Icon size={20} strokeWidth={1.5} />
        </motion.button>
      ))}
      <motion.button
        onClick={toggleTheme}
        whileHover={{ scale: 1.08, y: -1 }}
        whileTap={{ scale: 0.97 }}
        title="主题切换"
        className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow ring-1 ring-white/60"
      >
        {theme === 'dark' ? <Sun size={20} strokeWidth={1.5} /> : <Moon size={20} strokeWidth={1.5} />}
      </motion.button>
    </div>
  );
}
