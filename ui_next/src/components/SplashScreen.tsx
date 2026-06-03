import { motion, AnimatePresence } from 'framer-motion';

export function SplashScreen({ visible }: { visible: boolean }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="fixed inset-0 z-[100] grid place-items-center overflow-hidden bg-[#f0f4f9] dark:bg-[#0a0e1a]"
          exit={{ opacity: 0, scale: 1.03, filter: 'blur(12px)' }}
          transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(34,211,238,.28),transparent_28%),radial-gradient(circle_at_60%_56%,rgba(11,95,244,.20),transparent_34%)]" />
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
            className="relative flex flex-col items-center gap-5"
          >
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 12, repeat: Infinity, ease: 'linear' }}
              className="relative h-28 w-28 rounded-[34px] border border-white/50 bg-white/35 shadow-glow backdrop-blur-2xl dark:border-white/15 dark:bg-slate-900/40"
            >
              <motion.div
                animate={{ scale: [1, 1.08, 1], opacity: [0.86, 1, 0.86] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="absolute inset-4 rounded-[24px] bg-gradient-to-br from-ocean to-cyan-glow blur-[1px]"
              />
              <div className="absolute inset-[25px] rounded-2xl border border-white/70 bg-white/40 backdrop-blur-xl dark:bg-black/20" />
            </motion.div>
            <div className="text-center">
              <h1 className="text-2xl font-black tracking-tight text-slate-950 dark:text-slate-50">GIS 智能体</h1>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">正在加载空间智能工作台</p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
