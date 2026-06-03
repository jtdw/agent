import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

type State = {
  error: string;
};

export class ErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  state: State = { error: '' };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error.message : '界面加载失败' };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fixed inset-0 z-[120] grid place-items-center bg-slate-950/20 p-6 backdrop-blur-xl dark:bg-black/50">
        <div className="w-full max-w-lg rounded-[28px] border border-white/50 bg-white/80 p-6 shadow-glass backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/80">
          <div className="mb-4 flex items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-coral/10 text-coral">
              <AlertTriangle size={22} strokeWidth={1.7} />
            </div>
            <div>
              <div className="text-xl font-black">工作台加载遇到问题</div>
              <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">可以先刷新界面继续使用。</div>
            </div>
          </div>
          <div className="max-h-32 overflow-auto rounded-2xl bg-slate-950/5 p-3 text-xs text-slate-500 dark:bg-white/5 dark:text-slate-300">
            {this.state.error}
          </div>
          <button onClick={() => window.location.reload()} className="primary-button mt-5 w-full gap-2">
            <RotateCcw size={16} strokeWidth={1.7} /> 刷新界面
          </button>
        </div>
      </div>
    );
  }
}
