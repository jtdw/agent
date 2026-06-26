import { ChatMessageRenderer } from '../ChatMessageRenderer';
import { TaskSummaryRail } from './TaskSummaryRail';
import { buildChatTaskSummary } from './chatWorkspaceModel';
import type { ChatMessage, PresentationResult } from '@/lib/api';

const harnessMessage: ChatMessage = {
  id: 'task_harness_running_message',
  role: 'assistant',
  content: '',
  meta: {
    task_id: 'task_harness_running',
    status: 'running',
    progress: 46,
    phase: 'validate',
    current_step: '正在校验上传边界与目标栅格范围',
    realtime_sync: 'live',
    interaction_type: 'tool_task',
    task_card: {
      task_id: 'task_harness_running',
      title: '工作区数据检查与建模准备',
      current_step: '正在校验上传边界与目标栅格范围'
    },
    execution_summary: {
      summary: '读取当前工作区上下文，校验输入数据，再准备工具调用与成果注册。'
    },
    presentation_result: {
      artifact_refs: [
        { artifact_id: 'artifact_harness_report', title: 'boundary_check_report.md', type: 'document' },
        { artifact_id: 'artifact_harness_grid', title: 'target_grid_preview.tif', type: 'raster' }
      ],
      map_layer_refs: [
        { layer_id: 'layer_harness_boundary', name: 'Boundary validation preview' }
      ],
      next_action_suggestions: [
        'Review boundary check report',
        'Add validation preview to map'
      ]
    },
    management_view: {
      status: 'running',
      user_message: '正在检查字段、坐标系和空间范围。',
      available_actions: ['cancel']
    }
  }
};

const harnessResult: PresentationResult = {
  status: 'running',
  concise_summary: '智能体正在确认数据结构、坐标系和后续 GIS 工具参数。',
  result_highlights: ['已读取当前会话上下文', '正在校验字段与空间范围'],
  data_sources: ['workspace_upload_boundary.geojson', 'workspace_dem_preview.tif'],
  next_action_suggestions: ['确认边界与栅格范围一致', '完成后注册地图图层与下载成果'],
  executed_steps: [
    { step_id: 'read-context', tool_name: 'workspace_profile', status: 'succeeded' },
    { step_id: 'validate-inputs', tool_name: 'vector_validate', status: 'running' },
    { step_id: 'register-outputs', tool_name: 'artifact_register', status: 'queued' }
  ],
  warnings: []
};

export function TaskCardVisualHarness() {
  const taskSummaryItems = buildChatTaskSummary([harnessMessage]);
  return (
    <main data-testid="task-card-visual-harness" className="min-h-screen bg-slate-100 p-4 text-slate-950 dark:bg-slate-950 dark:text-slate-50">
      <section className="mx-auto grid h-[calc(100vh-2rem)] max-w-6xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,.16)] dark:border-slate-800 dark:bg-slate-900 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="flex min-h-0 min-w-0 flex-col">
          <header className="border-b border-slate-200/80 px-5 py-4 dark:border-slate-800">
            <div className="text-xs font-black uppercase tracking-[0.12em] text-blue-600 dark:text-cyan-300">GIS Agent Visual Harness</div>
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
        <TaskSummaryRail taskSummaryItems={taskSummaryItems} realtimeState="live" messageCount={2} />
      </section>
    </main>
  );
}
