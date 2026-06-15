import { AnimatePresence, motion } from 'framer-motion';
import { Globe2, Languages, Ruler, Settings, X } from 'lucide-react';
import { useState } from 'react';
import { GlassCard } from './GlassCard';
import { ModalPortal } from './ModalPortal';
import { CommercialUser } from '@/lib/api';
import { GSCloudAccountPanel } from './GSCloudAccountPanel';

export function SettingsPanel({ user }: { user: CommercialUser | null }) {
  const [open, setOpen] = useState(false);
  const [language, setLanguage] = useState('zh-CN');
  const rows = [
    { icon: Ruler, label: '距离单位', value: 'Metric' },
    { icon: Globe2, label: '坐标系统', value: '按数据自动识别' }
  ];

  return (
    <>
      <button onClick={() => setOpen(true)} className="glass-panel no-drag fixed right-5 top-16 z-40 grid h-12 w-12 place-items-center rounded-full text-slate-700 dark:text-slate-200" aria-label="打开设置"><Settings size={20} strokeWidth={1.5} /></button>
      <ModalPortal>
        <AnimatePresence>
          {open && (
            <motion.div className="fixed inset-0 z-[85] grid place-items-center overflow-y-auto bg-slate-950/20 p-3 backdrop-blur-sm dark:bg-black/45 sm:p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <motion.div initial={{ opacity: 0, scale: 0.95, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }} transition={{ duration: 0.15 }}>
                <GlassCard className="max-h-[calc(100dvh-1.5rem)] w-[min(420px,calc(100vw-1.5rem))] overflow-y-auto p-5 sm:max-h-[calc(100dvh-2rem)]">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <div className="text-xl font-black">设置</div>
                      <p className="text-sm text-slate-500 dark:text-slate-400">界面、单位、地图参数与我的数据源账号</p>
                    </div>
                    <button onClick={() => setOpen(false)} className="glass-button h-10 w-10 rounded-2xl p-0" aria-label="关闭设置"><X size={18} /></button>
                  </div>
                  <div className="space-y-2">
                    <div className="pb-1 text-xs font-black uppercase tracking-[0.16em] text-slate-400">我的数据源账号</div>
                    <GSCloudAccountPanel enabled={Boolean(user)} />
                    <div className="flex items-center justify-between gap-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-white/5">
                      <div className="flex items-center gap-3">
                        <div className="grid h-10 w-10 place-items-center rounded-2xl bg-cyan-glow/10 text-cyan-glow"><Languages size={18} /></div>
                        <div className="text-sm font-bold">语言</div>
                      </div>
                      <select
                        data-testid="settings-language-selector"
                        value={language}
                        onChange={(event) => setLanguage(event.target.value)}
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                        aria-label="选择界面语言"
                      >
                        <option value="zh-CN">简体中文</option>
                        <option value="en-US">English</option>
                      </select>
                    </div>
                    {rows.map(({ icon: Icon, label, value }) => (
                      <div key={label} className="flex items-center justify-between rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-white/5">
                        <div className="flex items-center gap-3">
                          <div className="grid h-10 w-10 place-items-center rounded-2xl bg-cyan-glow/10 text-cyan-glow"><Icon size={18} /></div>
                          <div className="text-sm font-bold">{label}</div>
                        </div>
                        <div className="text-sm text-slate-500 dark:text-slate-400">{value}</div>
                      </div>
                    ))}
                  </div>
                </GlassCard>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </ModalPortal>
    </>
  );
}
