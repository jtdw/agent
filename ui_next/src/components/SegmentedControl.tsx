import { motion } from 'framer-motion';
import { cn } from '@/lib/cn';

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  className
}: {
  value: T;
  options: { label: string; value: T }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cn('relative flex rounded-2xl border border-white/40 bg-white/35 p-1 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/35', className)}>
      {options.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            onClick={() => onChange(item.value)}
            className={cn('relative z-10 flex-1 rounded-xl px-3 py-2 text-sm font-bold transition', active ? 'text-white' : 'text-slate-600 hover:text-slate-950 dark:text-slate-400 dark:hover:text-slate-50')}
          >
            {active && <motion.span layoutId="segmented-pill" className="absolute inset-0 -z-10 rounded-xl bg-gradient-to-r from-ocean to-cyan-glow shadow-glow" transition={{ type: 'spring', stiffness: 320, damping: 32 }} />}
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
