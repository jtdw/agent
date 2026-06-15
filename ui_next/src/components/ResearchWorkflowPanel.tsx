import { motion } from 'framer-motion';
import { CheckCircle2, ClipboardList, FileText, Layers3, LocateFixed, Play, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { cn } from '@/lib/cn';
import { createResearchPlan, markStepDone, type ResearchPlan, type WorkflowAction } from './researchWorkflow';

const presets = [
  {
    title: '闪电河流域土壤水分融合',
    prompt: '闪电河流域土壤水分融合',
    desc: '适合展示论文复现、模型融合和 GCP 可靠性。'
  },
  {
    title: '成都市 DEM 与土壤水分展示',
    prompt: '我要分析成都市 2019 年土壤水分空间分布',
    desc: '适合面试演示：研究区、站点、DEM 和专题图。'
  },
  {
    title: '自定义 GIS 数据质检与制图',
    prompt: '检查当前上传数据并生成 GIS 制图展示流程',
    desc: '适合工作场景：快速判断数据能否交付。'
  }
];

function actionIcon(action: WorkflowAction) {
  if (action.kind === 'map') return LocateFixed;
  if (action.kind === 'layer') return Layers3;
  if (action.kind === 'workflow') return Sparkles;
  return FileText;
}

export function ResearchWorkflowPanel({
  onRunAction
}: {
  onRunAction: (action: WorkflowAction) => void;
}) {
  const [objective, setObjective] = useState('我要分析成都市 2019 年土壤水分空间分布');
  const [plan, setPlan] = useState<ResearchPlan>(() => createResearchPlan('我要分析成都市 2019 年土壤水分空间分布'));
  const doneCount = useMemo(() => plan.steps.filter((step) => step.status === 'done').length, [plan]);

  const createPlan = (value = objective) => {
    setObjective(value);
    setPlan(createResearchPlan(value));
  };

  const runStep = (stepId: string, action: WorkflowAction) => {
    onRunAction(action);
    setPlan((current) => markStepDone(current, stepId));
  };

  return (
    <div className="mt-4 rounded-[22px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-black"><ClipboardList size={16} strokeWidth={1.5} /> 研究任务向导</div>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">把一个研究目标拆成可执行、可展示的 GIS 工作流。</p>
        </div>
        <div className="rounded-full border border-cyan-glow/25 bg-cyan-glow/10 px-2 py-1 text-[11px] font-black text-ocean dark:text-cyan-glow">
          {doneCount}/{plan.steps.length}
        </div>
      </div>

      <div className="flex gap-2">
        <input
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          className="input-glass h-10 min-w-0 flex-1 text-xs"
          placeholder="输入研究目标，例如：成都市土壤水分空间分析"
        />
        <button onClick={() => createPlan()} className="primary-button h-10 shrink-0 rounded-2xl px-3 text-xs">
          生成
        </button>
      </div>

      <div className="mt-3 grid gap-2">
        {presets.map((preset) => (
          <button
            key={preset.title}
            onClick={() => createPlan(preset.prompt)}
            className="rounded-2xl border border-white/30 bg-white/30 px-3 py-2 text-left transition-colors hover:bg-white/55 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
          >
            <div className="truncate text-xs font-black text-slate-700 dark:text-slate-100">{preset.title}</div>
            <div className="mt-0.5 line-clamp-1 text-[11px] text-slate-500 dark:text-slate-400">{preset.desc}</div>
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-2xl border border-white/25 bg-white/25 p-3 dark:border-white/10 dark:bg-white/5">
        <div className="text-sm font-black text-slate-800 dark:text-slate-100">{plan.title}</div>
        <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{plan.summary}</div>
      </div>

      <div className="mt-3 space-y-2">
        {plan.steps.map((step, index) => {
          const Icon = actionIcon(step.action);
          const done = step.status === 'done';
          const running = step.status === 'running';
          return (
            <motion.div
              key={step.id}
              layout
              className={cn(
                'rounded-2xl border p-3 transition-colors',
                done ? 'border-emerald-300/35 bg-emerald-400/10' : running ? 'border-cyan-glow/35 bg-cyan-glow/10 shadow-glow' : 'border-white/25 bg-white/25 dark:border-white/10 dark:bg-white/5'
              )}
            >
              <div className="flex items-start gap-3">
                <div className={cn('grid h-8 w-8 shrink-0 place-items-center rounded-2xl text-xs font-black', done ? 'bg-emerald-400/20 text-emerald-600 dark:text-emerald-200' : 'bg-white/45 text-slate-500 dark:bg-white/10 dark:text-slate-300')}>
                  {done ? <CheckCircle2 size={16} strokeWidth={1.8} /> : index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Icon size={14} strokeWidth={1.7} className="shrink-0 text-ocean dark:text-cyan-glow" />
                    <div className="truncate text-xs font-black text-slate-800 dark:text-slate-100">{step.title}</div>
                  </div>
                  <div className="mt-1 text-[11px] leading-5 text-slate-500 dark:text-slate-400">{step.description}</div>
                  <div className="mt-2 rounded-xl bg-white/35 px-2 py-1.5 text-[11px] leading-5 text-slate-500 dark:bg-white/5 dark:text-slate-400">
                    {step.talkTrack}
                  </div>
                </div>
              </div>
              <button
                onClick={() => runStep(step.id, step.action)}
                className="glass-button mt-3 h-8 w-full gap-2 rounded-2xl text-xs font-black"
              >
                <Play size={13} strokeWidth={1.8} /> {done ? '重新执行' : running ? '执行当前步骤' : '执行此步骤'}
              </button>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
