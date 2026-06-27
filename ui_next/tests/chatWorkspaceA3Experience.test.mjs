import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function loadTs(path) {
  const source = await readFile(path, 'utf8');
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true
    }
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);
}

const panel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const rail = await readFile('src/components/chat/TaskSummaryRail.tsx', 'utf8');
const workbenchHook = await readFile('src/components/chat/useChatTaskWorkbench.ts', 'utf8');
const useChatModelsSource = await readFile('src/components/chat/useChatModels.ts', 'utf8');
const harness = await readFile('src/components/chat/TaskCardVisualHarness.tsx', 'utf8');
const harnessEntry = await readFile('src/components/chat/taskCardVisualHarnessEntry.tsx', 'utf8');
const harnessHtml = await readFile('task-card-harness.html', 'utf8');
const model = await loadTs('src/components/chat/chatWorkspaceModel.ts');

assert.match(harnessHtml, /taskCardVisualHarnessEntry\.tsx/, 'Visual harness should use an isolated Vite HTML entry');
assert.match(harnessEntry, /createRoot/, 'Visual harness entry should mount independently from the production App');
assert.match(harnessEntry, /TaskCardVisualHarness/, 'Visual harness entry should render the task-card harness');
assert.match(harness, /data-testid="task-card-visual-harness"/, 'Harness should expose a stable screenshot root');
assert.match(harness, /<ChatMessageRenderer/, 'Harness should render the real task card component');
assert.match(harness, /lg:flex-row/, 'Harness should use a stable flex layout for screenshot sizing');
assert.doesNotMatch(harness, /lg:grid-cols-\[/, 'Harness should not use arbitrary grid columns that can squeeze the task card');
assert.match(harness, /task_harness_running/, 'Harness should use a stable synthetic task id');
assert.doesNotMatch(harness, /\.env|token=|cookie|storage_state|Traceback|C:\\\\/, 'Harness fixture must not contain sensitive implementation strings');

assert.match(panel, /useChatTaskWorkbench/, 'ChatPanel should delegate chat task workbench derivation to a focused hook');
assert.doesNotMatch(panel, /useMemo\(\(\) => buildChatTaskSummary/, 'ChatPanel should not own task rail derivation after hook extraction');
assert.match(workbenchHook, /export function useChatTaskWorkbench/, 'useChatTaskWorkbench should be exported as a focused hook');
assert.match(workbenchHook, /buildRenderMessages/, 'useChatTaskWorkbench should own render-message derivation');
assert.match(workbenchHook, /buildChatTaskSummary/, 'useChatTaskWorkbench should own task summary derivation');
assert.match(panel, /useChatModels/, 'ChatPanel should delegate chat model state to useChatModels');
assert.doesNotMatch(panel, /api\.chatModels|api\.selectChatModel/, 'ChatPanel should not own chat model API calls after hook extraction');
assert.doesNotMatch(panel, /setChatModels/, 'ChatPanel should not directly mutate chat model state after hook extraction');
assert.match(useChatModelsSource, /export function useChatModels/, 'useChatModels hook should be exported');
assert.match(useChatModelsSource, /api\.chatModels/, 'useChatModels should load available chat models');
assert.match(useChatModelsSource, /api\.selectChatModel/, 'useChatModels should own model switching');
assert.match(useChatModelsSource, /visibleModels/, 'useChatModels should return de-duplicated visibleModels');
assert.match(useChatModelsSource, /modelNotice/, 'useChatModels should own transient model success notice');
assert.match(useChatModelsSource, /modelError/, 'useChatModels should own model switching errors');
assert.match(panel, /<TaskSummaryRail/, 'ChatPanel should render the task summary rail');
assert.match(panel, /lg:grid-cols-\[180px_minmax\(0,1fr\)_280px\]/, 'Page chat layout should keep an about-180px session rail and reserve more room for messages');
assert.match(panel, /fillHeight\?: boolean/, 'ChatWorkspace should support an embedded full-height layout');
assert.match(panel, /fillHeight \? 'h-full rounded-none border-0 shadow-none lg:h-full lg:min-h-0'/, 'Embedded page chat should fill its host without a card-like surrounding gutter');
assert.match(rail, /export function TaskSummaryRail/, 'TaskSummaryRail should be an isolated component');
assert.match(rail, /taskSummaryItems/, 'TaskSummaryRail should render derived task summary items');
assert.match(rail, /data-testid="chat-task-summary-rail"/, 'TaskSummaryRail should keep a stable task rail test id');
assert.match(rail, /lg:col-start-3/, 'Right rail should live in the third desktop column');
assert.match(rail, /data-testid="chat-task-summary-item"/, 'TaskSummaryRail should expose stable item test ids');
assert.match(rail, /artifactCount|mapLayerCount|nextActions/, 'TaskSummaryRail should surface artifacts, map layers, and next actions');
assert.match(rail, /data-testid="chat-task-summary-artifacts"/, 'TaskSummaryRail should expose artifact summary test id');
assert.match(rail, /data-testid="chat-task-summary-next-actions"/, 'TaskSummaryRail should expose next-action summary test id');
assert.match(rail, /data-testid="chat-task-workbench-header"/, 'TaskSummaryRail should expose a stable workbench header for screenshot checks');
assert.match(rail, /data-testid="chat-task-process-lane"/, 'TaskSummaryRail should render a public process lane for each task');
assert.match(rail, /data-testid="chat-task-result-strip"/, 'TaskSummaryRail should render a compact result strip for artifacts and map layers');
assert.match(rail, /task-rail-spine/, 'TaskSummaryRail should include a visual status spine for the A3 workbench style');
assert.match(rail, /GIS/, 'TaskSummaryRail copy should make the GIS workbench purpose visible');
assert.match(rail, /实时过程流/, 'TaskSummaryRail subtitle should be Chinese');
assert.doesNotMatch(rail, /Live process rail/, 'TaskSummaryRail should not show English rail subtitles');
assert.match(harness, /GIS 智能体视觉验收/, 'Visual harness title should be Chinese');
assert.doesNotMatch(harness, /GIS Agent Visual Harness/, 'Visual harness should not expose English title copy');
assert.match(harness, /边界校验预览/, 'Visual harness map layer fixture should be Chinese');
assert.match(harness, /查看边界检查报告/, 'Visual harness next action should be Chinese');
assert.match(harness, /添加校验预览图层/, 'Visual harness map action should be Chinese');

const messages = [
  { id: 'u1', role: 'user', content: '执行分析' },
  {
    id: 'task-1',
    role: 'assistant',
    content: '',
    meta: {
      task_id: 'task_harness_running',
      status: 'running',
      progress: 42,
      current_step: '正在校验上传的矢量边界',
      realtime_sync: 'live',
      interaction_type: 'tool_task',
      task_card: {
        title: '工作区数据校验',
        current_step: '正在校验上传的矢量边界'
      },
      execution_summary: {
        summary: '读取工作区上下文，校验输入数据，然后注册结果成果。'
      },
      presentation_result: {
        artifact_refs: [
          { artifact_id: 'artifact_1', title: '模型报告.md', type: 'document' },
          { artifact_id: 'artifact_2', title: '预测结果.tif', type: 'raster' }
        ],
        map_layer_refs: [
          { layer_id: 'layer_1', name: '预测结果图层' }
        ],
        next_action_suggestions: ['查看模型报告', '添加预测图层到地图']
      }
    }
  },
  {
    id: 'task-secret',
    role: 'assistant',
    content: '',
    meta: {
      task_id: 'task_secret',
      status: 'failed',
      interaction_type: 'tool_task',
      task_card: {
        title: 'C:\\Users\\demo\\.env token=secret',
        current_step: 'Traceback cookie storage_state.json'
      }
    }
  },
  { id: 'task-1', role: 'assistant', content: 'duplicate should collapse', meta: { task_id: 'task_harness_running' } }
];

const renderMessages = model.buildRenderMessages(messages);
assert.equal(renderMessages.length, 3, 'render-message model should de-duplicate by stable message key');

const taskSummaryItems = model.buildChatTaskSummary(messages);
assert.equal(taskSummaryItems.length, 2, 'task rail should include only assistant tool task messages');
const runningItem = taskSummaryItems.find((item) => item.id === 'task_harness_running');
assert.ok(runningItem, 'task rail should include the running synthetic task');
assert.equal(runningItem.status, 'running');
assert.equal(runningItem.progress, 42);
assert.match(runningItem.summary, /工作区数据校验|正在校验上传的矢量边界|读取工作区上下文/);
assert.equal(runningItem.artifactCount, 2, 'task rail should count registered artifacts');
assert.equal(runningItem.mapLayerCount, 1, 'task rail should count generated map layers');
assert.deepEqual(runningItem.nextActions, ['查看模型报告', '添加预测图层到地图']);
assert.match(runningItem.primaryResultLabel, /模型报告\.md|预测结果\.tif|预测结果图层/, 'task rail should expose a human-readable primary result label');

const serialized = JSON.stringify(taskSummaryItems);
assert.doesNotMatch(serialized, /C:\\|\.env|token=|cookie|storage_state|Traceback/i, 'task rail summaries must redact sensitive details');
assert.match(serialized, /敏感细节已隐藏|Sensitive details hidden/, 'redacted task rail summaries should remain understandable');

console.log('chatWorkspaceA3Experience.test.mjs passed');
