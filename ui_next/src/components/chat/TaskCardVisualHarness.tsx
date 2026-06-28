import { ChatMessageRenderer } from '../ChatMessageRenderer';
import { TaskSummaryRail } from './TaskSummaryRail';
import { buildChatTaskSummary } from './chatWorkspaceModel';
import type { ChatMessage, PresentationResult } from '@/lib/api';

const harnessResult: PresentationResult = {
  status: 'succeeded',
  concise_summary: '已完成 XGBoost 土壤水分全流域预测，并生成预测栅格、PNG 预览、summary JSON 和地图图层。',
  executed_steps: [
    {
      step_id: 'predict_raster_map',
      tool_name: 'predict_xgboost_raster_map',
      status: 'succeeded'
    }
  ],
  result_highlights: [
    'result_dataset=xgboost_raster_prediction',
    'target=soil_moisture_mean',
    'representative_date=2019-07-15',
    'valid_prediction_pixels=49'
  ],
  artifact_refs: [
    {
      artifact_id: 'artifact_prediction_raster',
      title: 'xgboost_raster_prediction.tif',
      type: 'raster',
      source_step_id: 'predict_raster_map',
      source_tool: 'predict_xgboost_raster_map'
    },
    {
      artifact_id: 'artifact_prediction_preview',
      title: 'xgboost_raster_prediction.png',
      type: 'png',
      source_step_id: 'predict_raster_map',
      source_tool: 'predict_xgboost_raster_map'
    },
    {
      artifact_id: 'artifact_prediction_summary',
      title: 'xgboost_raster_prediction_summary.json',
      type: 'summary',
      source_step_id: 'predict_raster_map',
      source_tool: 'predict_xgboost_raster_map'
    }
  ],
  map_layer_refs: [
    {
      layer_id: 'dataset_xgboost_raster_prediction',
      name: 'xgboost_raster_prediction',
      source_step_id: 'predict_raster_map',
      source_tool: 'predict_xgboost_raster_map'
    }
  ],
  image_refs: [
    {
      artifact_id: 'artifact_prediction_preview',
      title: 'xgboost_raster_prediction.png',
      source_step_id: 'predict_raster_map',
      source_tool: 'predict_xgboost_raster_map'
    }
  ],
  next_action_suggestions: ['打开预测地图图层', '下载 GeoTIFF 与 summary JSON']
};

const harnessMessage: ChatMessage = {
  id: 'task_harness_running_message',
  role: 'assistant',
  content: '',
  meta: {
    task_id: 'task_harness_running',
    status: 'succeeded',
    progress: 100,
    phase: 'presentation',
    current_step: '已生成 XGBoost 预测地图与可下载成果',
    realtime_sync: 'live',
    interaction_type: 'tool_task',
    task_card: {
      task_id: 'task_harness_running',
      title: 'STM XGBoost 全流域预测图',
      current_step: '已生成 XGBoost 预测地图与可下载成果'
    },
    execution_summary: {
      summary: '已完成预测制图，前端应把 GeoTIFF、PNG、summary JSON 和地图图层分组展示。'
    },
    presentation_result: harnessResult,
    management_view: {
      status: 'succeeded',
      user_message: '预测地图、预览图和模型报告已注册到当前会话。',
      available_actions: ['view_artifacts', 'add_to_map']
    }
  }
};

export function TaskCardVisualHarness() {
  const taskSummaryItems = buildChatTaskSummary([harnessMessage]);
  return (
    <main data-testid="task-card-visual-harness" className="min-h-screen bg-slate-100 p-4 text-slate-950 dark:bg-slate-950 dark:text-slate-50">
      <section className="mx-auto flex h-[calc(100vh-2rem)] max-w-6xl flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,.16)] dark:border-slate-800 dark:bg-slate-900 lg:flex-row">
        <div className="flex min-h-0 min-w-0 flex-col">
          <header className="border-b border-slate-200/80 px-5 py-4 dark:border-slate-800">
            <div className="text-xs font-black text-blue-600 dark:text-cyan-300">GIS 智能体视觉验收</div>
            <h1 className="mt-1 text-lg font-black">实时任务卡与公开过程</h1>
          </header>
          <div className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-gradient-to-b from-slate-50 to-white p-5 dark:from-slate-950/30 dark:to-slate-900/30">
            <div className="task-card-harness-frame mx-auto min-w-0 w-full max-w-3xl">
            <ChatMessageRenderer
              message={harnessMessage}
              content=""
              isUser={false}
              isSystem={false}
              sessionId="session_harness"
            />
            </div>
          </div>
          <div className="border-t border-slate-200/80 bg-white/90 p-4 dark:border-slate-800 dark:bg-slate-900/90">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-bold text-slate-500 dark:border-slate-800 dark:bg-slate-950/42 dark:text-slate-300">
              有问题，尽管问
            </div>
          </div>
        </div>
        <div className="hidden min-h-0 w-[280px] shrink-0 lg:block">
          <TaskSummaryRail taskSummaryItems={taskSummaryItems} realtimeState="live" messageCount={2} />
        </div>
      </section>
    </main>
  );
}
