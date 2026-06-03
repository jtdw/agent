import type { LayerVisibility } from './mapLayerPolicy';
import type { MapCommandType } from './mapCommands';

export type WorkflowStepStatus = 'pending' | 'running' | 'done' | 'blocked';

export type WorkflowAction =
  | { kind: 'prompt'; prompt: string }
  | { kind: 'map'; command: MapCommandType }
  | { kind: 'layer'; layer: keyof LayerVisibility; visible: boolean }
  | { kind: 'workflow'; workflowId: 'shandian-soil-moisture'; prompt: string };

export type ResearchWorkflowStep = {
  id: string;
  title: string;
  description: string;
  status: WorkflowStepStatus;
  talkTrack: string;
  action: WorkflowAction;
};

export type ResearchPlan = {
  presetId: 'chengdu-soil-moisture' | 'shandian-soil-moisture' | 'data-quality-map';
  title: string;
  objective: string;
  summary: string;
  steps: ResearchWorkflowStep[];
};

const commonTalkTracks = {
  data: '我会先说明数据是否可用，再展示后续分析为什么可信。',
  region: '研究区和底图先对齐，面试展示时能快速建立空间背景。',
  layer: '图层切换展示的是数据组织能力，不只是静态图片。',
  analysis: '这里强调从数据到结果的流程，而不是只展示最终地图。',
  explain: '最后把结果转成可讲述的话术，方便答辩或工作汇报。',
  package: '展示包用于留存成果，也能说明这个系统具备可交付能力。'
};

function makeStep(
  id: string,
  title: string,
  description: string,
  action: WorkflowAction,
  talkTrack: string,
  status: WorkflowStepStatus = 'pending'
): ResearchWorkflowStep {
  return { id, title, description, action, talkTrack, status };
}

function normalizeObjective(input: string) {
  return input.trim() || '完成一个 GIS 数据检查、制图和展示流程';
}

function detectPreset(objective: string): ResearchPlan['presetId'] {
  const text = objective.toLowerCase();
  if (text.includes('闪电河') || text.includes('shandian')) return 'shandian-soil-moisture';
  if (text.includes('成都') || text.includes('土壤水分')) return 'chengdu-soil-moisture';
  return 'data-quality-map';
}

function titleForPreset(presetId: ResearchPlan['presetId']) {
  if (presetId === 'shandian-soil-moisture') return '闪电河流域土壤水分融合';
  if (presetId === 'chengdu-soil-moisture') return '成都市土壤水分空间分析';
  return 'GIS 数据质检与制图展示';
}

export function createResearchPlan(input: string): ResearchPlan {
  const objective = normalizeObjective(input);
  const presetId = detectPreset(objective);
  const title = titleForPreset(presetId);
  const workflowPrompt = presetId === 'shandian-soil-moisture'
    ? '一键检查并运行闪电河流域土壤水分融合论文流程。'
    : '根据当前工作区数据，生成一套适合面试展示的 GIS 分析流程。';

  const steps: ResearchWorkflowStep[] = [
    makeStep(
      'data-check',
      '检查工作区数据',
      '概括已上传和本地载入的数据，判断是否适合制图、建模和结果解释。',
      { kind: 'prompt', prompt: `请检查当前工作区数据，围绕“${objective}”判断数据完整性、字段、坐标、缺失值和可用于展示的内容。` },
      commonTalkTracks.data,
      'running'
    ),
    makeStep(
      'region-context',
      '确认研究区与底图',
      '定位地图到可用数据范围，展示研究区、站点和底图空间关系。',
      { kind: 'map', command: 'locate' },
      commonTalkTracks.region
    ),
    makeStep(
      'layer-ready',
      '打开关键图层',
      '显示站点、边界、DEM 和土壤水分结果，形成可讲解的地图画面。',
      { kind: 'layer', layer: 'soil', visible: true },
      commonTalkTracks.layer
    ),
    makeStep(
      'analysis-flow',
      presetId === 'shandian-soil-moisture' ? '运行论文流程' : '生成分析路线',
      presetId === 'shandian-soil-moisture' ? '调用闪电河土壤水分融合流程，检查 BTCH、RF、XGBoost、LSTM 与 GCP。' : '让智能体给出空间分析、图层组织和结果解释顺序。',
      presetId === 'shandian-soil-moisture'
        ? { kind: 'workflow', workflowId: 'shandian-soil-moisture', prompt: workflowPrompt }
        : { kind: 'prompt', prompt: workflowPrompt },
      commonTalkTracks.analysis
    ),
    makeStep(
      'explain-result',
      '生成展示讲解',
      '把当前地图和数据结果转成 1 分钟面试讲解话术。',
      { kind: 'prompt', prompt: `请把“${objective}”整理成适合研究生面试或工作汇报的 1 分钟讲解，包含数据、方法、地图结果和亮点。` },
      commonTalkTracks.explain
    ),
    makeStep(
      'deliverable',
      '准备成果导出',
      '提示用户导出地图截图、数据摘要和研究说明，形成可交付展示包。',
      { kind: 'prompt', prompt: `请基于“${objective}”列出展示包应包含的文件、地图、图表和说明文字。` },
      commonTalkTracks.package
    )
  ];

  return {
    presetId,
    title,
    objective,
    summary: '按“数据检查 → 空间定位 → 图层准备 → 分析流程 → 结果讲解 → 成果交付”的顺序推进。',
    steps
  };
}

export function markStepDone(plan: ResearchPlan, stepId: string): ResearchPlan {
  let promoted = false;
  const steps = plan.steps.map((step) => {
    if (step.id === stepId) return { ...step, status: 'done' as WorkflowStepStatus };
    if (!promoted && step.status === 'pending') {
      promoted = true;
      return { ...step, status: 'running' as WorkflowStepStatus };
    }
    return step;
  });
  return { ...plan, steps };
}

export function applyWorkflowAction(action: WorkflowAction) {
  return action;
}
