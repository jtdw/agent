import { motion, type HTMLMotionProps } from 'framer-motion';
import { cn } from '@/lib/cn';

export function GlassCard({ className, children, ...props }: HTMLMotionProps<'div'>) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      className={cn('glass-panel rounded-[20px]', className)}
      {...props}
    >
      {children}
    </motion.div>
  );
}
