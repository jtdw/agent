import { cn } from '@/lib/cn';

type RealtimeSyncState = 'connecting' | 'live' | 'polling';

export function RealtimeSyncIndicator({ state }: { state: RealtimeSyncState }) {
  const label = state === 'live' ? '实时同步' : state === 'connecting' ? '正在连接' : '定时同步';
  const tone = state === 'live'
    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200'
    : state === 'connecting'
      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200'
      : 'bg-amber-50 text-amber-700 dark:bg-amber-950/35 dark:text-amber-200';
  return <span data-testid="realtime-sync-indicator" className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-black', tone)}>{label}</span>;
}
