import { AnimatePresence, motion } from 'framer-motion';
import { Activity, AreaChart, CheckCircle2, ChevronRight, Download, FileText, RefreshCcw, X } from 'lucide-react';
import { lazy, Suspense, useMemo, useState } from 'react';
import { GlassCard } from './GlassCard';
import { api, ResultPanel, WorkspaceDashboard } from '@/lib/api';
import { buildAnalysisPanelView } from './analysisPanelData';
import type { ChatContextPayload } from '@/lib/chatContext';

const ModelMetricChart = lazy(() => import('./ModelMetricChart').then((m) => ({ default: m.ModelMetricChart })));

function SkeletonRows() {
  return <div className="space-y-3">{[1, 2, 3].map((i) => <div key={i} className="h-12 overflow-hidden rounded-2xl bg-white/35 dark:bg-white/5"><div className="h-full w-1/2 animate-shimmer bg-gradient-to-r from-transparent via-white/50 to-transparent" /></div>)}</div>;
}

function ChartSkeleton() {
  return <div className="h-full overflow-hidden rounded-2xl bg-white/35 dark:bg-white/5"><div className="h-full w-1/2 animate-shimmer bg-gradient-to-r from-transparent via-white/50 to-transparent" /></div>;
}

export function AnalysisPanel({ userId = '', sessionId = '', resultPanel = null, onChatContextChange }: { userId?: string; sessionId?: string; resultPanel?: ResultPanel | null; onChatContextChange?: (patch: Partial<ChatContextPayload>) => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [downloadingArtifactId, setDownloadingArtifactId] = useState('');
  const [dashboard, setDashboard] = useState<WorkspaceDashboard | null>(null);
  const [error, setError] = useState('');
  const view = useMemo(() => buildAnalysisPanelView(dashboard || {}, resultPanel), [dashboard, resultPanel]);

  const refresh = async () => {
    setLoading(true);
    setError('');
    if (!userId) {
      setDashboard(null);
      setLoading(false);
      return;
    }
    try {
      setDashboard(await api.dashboard(userId, sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : '读取分析结果失败');
    } finally {
      setLoading(false);
    }
  };

  const show = () => {
    setOpen(true);
    refresh();
  };

  const downloadArtifact = async (artifactId: string, label: string) => {
    if (!artifactId || downloadingArtifactId) return;
    setDownloadingArtifactId(artifactId);
    setError('');
    try {
      await api.downloadArtifactById(artifactId, label || '成果文件', userId, sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '文件已清理、无访问权限或下载链接已失效。');
    } finally {
      setDownloadingArtifactId('');
    }
  };

  return (
    <>
      <button data-testid="analysis-panel-open" onClick={show} className="primary-button no-drag fixed bottom-5 left-[430px] z-40 gap-2"><AreaChart size={17} strokeWidth={1.5} /> {resultPanel?.has_results ? '处理结果' : '分析结果'}</button>
      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-[80] bg-slate-950/20 p-6 backdrop-blur-sm dark:bg-black/45" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ x: 420, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 420, opacity: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }} className="absolute bottom-6 right-6 top-14 w-[min(500px,calc(100vw-1.5rem))]">
              <GlassCard className="flex h-full flex-col overflow-hidden p-0">
                <div className="flex items-center justify-between border-b border-white/30 px-5 py-4 dark:border-white/10">
                  <div>
                    <div className="flex items-center gap-2 text-xl font-black"><Activity size={20} strokeWidth={1.5} /> 分析结果</div>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">读取工作区真实流水线、模型指标和成果文件</p>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={refresh} disabled={loading} className="glass-button h-10 w-10 rounded-2xl p-0 disabled:opacity-50" title="刷新结果"><RefreshCcw size={17} className={loading ? 'animate-spin' : ''} /></button>
                    <button data-testid="analysis-panel-close" onClick={() => setOpen(false)} className="glass-button h-10 w-10 rounded-2xl p-0" title="关闭"><X size={18} /></button>
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto p-5">
                  {loading ? <SkeletonRows /> : error ? (
                    <div className="rounded-[22px] border border-coral/30 bg-coral/10 p-4 text-sm leading-6 text-coral">{error}</div>
                  ) : !view.hasResults ? (
                    <div className="rounded-[24px] border border-dashed border-white/40 bg-white/30 p-5 text-sm leading-6 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-slate-400">
                      <FileText size={24} strokeWidth={1.5} className="mb-3 text-ocean dark:text-cyan-glow" />
                      当前工作区还没有可展示的分析结果。先在智能体中运行“论文流程”、模型训练或生成图表后，这里会显示真实指标、流水线步骤和成果下载。
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="rounded-[22px] border border-white/30 bg-white/35 p-4 dark:border-white/10 dark:bg-slate-950/20">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-base font-black">{view.title}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {view.metricsDataset ? `指标表：${view.metricsDataset}` : '尚未识别到统一指标表'}
                            </div>
                          </div>
                          {view.status && <span className="rounded-full border border-emerald-300/35 bg-emerald-400/10 px-2 py-1 text-[11px] font-black text-emerald-700 dark:text-emerald-200">{view.status}</span>}
                        </div>
                      {view.bestModel && (
                          <button
                            data-testid="analysis-model-result"
                            type="button"
                            disabled={!view.bestModel?.modelResultId}
                            onClick={() => {
                              if (!view.bestModel?.modelResultId) return;
                              onChatContextChange?.({ selected_model_result_id: view.bestModel.modelResultId, last_visible_panel: 'analysis', user_focus_hint: '已选择模型结果' });
                            }}
                            className="mt-3 w-full rounded-2xl bg-cyan-glow/10 px-3 py-2 text-left text-xs leading-5 text-slate-600 transition hover:bg-cyan-glow/15 dark:text-slate-300"
                          >
                            当前最优模型：<b>{view.bestModel.name}</b>，优先按 RMSE 最小判断。
                          </button>
                        )}
                      </div>

                      {view.cards.length > 0 && (
                        <div className="grid grid-cols-3 gap-3">
                          {view.cards.map((card) => (
                            <div key={card.label} className="rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-white/5">
                              <div className="text-xs text-slate-500 dark:text-slate-400">{card.label}</div>
                              <div className="mt-1 text-2xl font-black">{card.value}</div>
                            </div>
                          ))}
                        </div>
                      )}

                      {view.chartData.length > 0 && (
                        <div className="rounded-[22px] border border-white/30 bg-white/35 p-4 dark:border-white/10 dark:bg-slate-950/20">
                          <div className="mb-3 text-sm font-black">模型指标对比</div>
                          <div className="h-64">
                            <Suspense fallback={<ChartSkeleton />}>
                              <ModelMetricChart data={view.chartData} />
                            </Suspense>
                          </div>
                        </div>
                      )}

                      {view.steps.length > 0 && (
                        <div className="rounded-[22px] border border-white/30 bg-white/35 p-4 dark:border-white/10 dark:bg-slate-950/20">
                          <div className="mb-3 text-sm font-black">流水线步骤</div>
                          <div className="space-y-2">
                            {view.steps.map((step) => (
                              <div key={`${step.name}-${step.status || step.summary || ''}`} className="rounded-2xl bg-white/35 px-3 py-2 text-xs leading-5 dark:bg-white/5">
                                <div className="flex items-center gap-2 font-black"><CheckCircle2 size={14} strokeWidth={1.7} className="text-emerald-500" /> {step.name}</div>
                                <div className="mt-1 text-slate-500 dark:text-slate-400">{step.summary || step.status}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {view.recommendations.length > 0 && (
                        <div className="rounded-[22px] border border-cyan-glow/25 bg-cyan-glow/10 p-4 dark:border-cyan-glow/20 dark:bg-cyan-glow/5">
                          <div className="mb-3 text-sm font-black">下一步建议</div>
                          <div className="space-y-2">
                            {view.recommendations.map((item) => (
                              <div key={item} className="rounded-2xl bg-white/35 px-3 py-2 text-xs leading-5 text-slate-600 dark:bg-white/5 dark:text-slate-300">
                                {item}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {view.downloads.length > 0 && (
                        <div className="space-y-2">
                          {view.downloads.map((item) => (
                            <button
                              data-testid="analysis-artifact-item"
                              key={item.artifactId}
                              type="button"
                              disabled={!item.artifactId || downloadingArtifactId === item.artifactId}
                              onClick={() => {
                                onChatContextChange?.({
                                  selected_artifact_id: item.artifactId || item.label,
                                  selected_artifact_type: item.kind,
                                  last_visible_panel: 'analysis',
                                  user_focus_hint: `selected artifact ${item.label}`
                                });
                                downloadArtifact(item.artifactId, item.label);
                              }}
                              className="flex w-full items-center justify-between rounded-[18px] border border-white/30 bg-white/35 px-4 py-3 text-left text-sm font-bold transition hover:bg-white/60 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                            >
                              <span className="flex min-w-0 items-center gap-2"><Download size={16} className="shrink-0" /> <span className="truncate">{item.label}</span></span><ChevronRight size={16} className="shrink-0" />
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </GlassCard>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
