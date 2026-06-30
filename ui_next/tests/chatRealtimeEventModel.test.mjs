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
  return {
    source,
    module: await import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`)
  };
}

const { source, module: model } = await loadTs('src/components/chat/chatRealtimeEventModel.ts');

assert.match(source, /TRANSIENT_EVENT_VERSION_FLOOR/, 'Realtime model should document the transient version namespace');
assert.match(source, /shouldAcceptRealtimeEvent/, 'Realtime model should expose event gate logic');

const state = model.createRealtimeEventGateState();
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'token-1', version: 1_000_000_001, kind: 'model_token' }, state), true);
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'task-1', version: 12, kind: 'task_progress' }, state), true);
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'task-old', version: 11, kind: 'task_progress' }, state), false);
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'token-2', version: 1_000_000_002, kind: 'model_complete' }, state), true);
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'task-2', version: 13, kind: 'task_result' }, state), true);
assert.equal(model.shouldAcceptRealtimeEvent({ event_id: 'task-2', version: 13, kind: 'task_result' }, state), false);

const contaminatedMeta = {
  task_id: 'chat-1',
  interaction_type: 'tool_task',
  mode: 'background_worker',
  status: 'running',
  task_card: { task_id: 'chat-1', status: 'running' },
  management_view: { task_id: 'chat-1', status: 'running' },
  download_management_view: { task_id: 'chat-1', status: 'running' },
  action_required: { type: 'confirmation_required' },
  streaming: true
};
const cleanChatMeta = model.mergeRealtimeEventMeta(
  contaminatedMeta,
  {
    task_id: 'chat-1',
    status: 'succeeded',
    streaming: false,
    mode: 'answer_only',
    response_mode: 'answer_only',
    interaction_type: 'chat_answer',
    reason: 'chat_only_direct_answer'
  },
  { kind: 'model_complete', task_id: 'chat-1' }
);
assert.equal(cleanChatMeta.interaction_type, 'chat_answer');
assert.equal(cleanChatMeta.mode, 'answer_only');
assert.equal(cleanChatMeta.response_mode, 'answer_only');
assert.equal(cleanChatMeta.task_id, undefined);
assert.equal(cleanChatMeta.job_id, undefined);
assert.equal(cleanChatMeta.status, undefined);
assert.equal(cleanChatMeta.progress, undefined);
assert.equal(cleanChatMeta.task_card, undefined);
assert.equal(cleanChatMeta.management_view, undefined);
assert.equal(cleanChatMeta.download_management_view, undefined);
assert.equal(cleanChatMeta.action_required, undefined);

const chatPlaceholderMeta = model.mergeRealtimeEventMeta(
  {
    task_id: 'chat-pending',
    streaming: true,
    realtime_sync: 'live'
  },
  {
    task_id: 'chat-pending',
    status: 'planning',
    progress: 10,
    phase: 'routing',
    current_step: 'Preparing response or task plan.',
    realtime_sync: 'live'
  },
  { kind: 'task_status', task_id: 'chat-pending' }
);
assert.equal(chatPlaceholderMeta.task_id, 'chat-pending');
assert.equal(chatPlaceholderMeta.streaming, true);
assert.equal(chatPlaceholderMeta.realtime_sync, 'live');
assert.equal(chatPlaceholderMeta.status, undefined);
assert.equal(chatPlaceholderMeta.progress, undefined);
assert.equal(chatPlaceholderMeta.phase, undefined);
assert.equal(chatPlaceholderMeta.current_step, undefined);
assert.equal(
  model.shouldUseRealtimeEventContent(
    { task_id: 'chat-pending', streaming: true },
    { task_id: 'chat-pending', status: 'planning' },
    { kind: 'task_status', task_id: 'chat-pending' }
  ),
  false,
  'Generic task status text must not replace a chat answer placeholder'
);

const explicitToolMeta = model.mergeRealtimeEventMeta(
  {
    task_id: 'chat-task',
    streaming: true
  },
  {
    task_id: 'chat-task',
    status: 'planning',
    progress: 10,
    phase: 'routing',
    interaction_type: 'tool_task',
    task_card: { task_id: 'chat-task', status: 'planning' }
  },
  { kind: 'task_status', task_id: 'chat-task' }
);
assert.equal(explicitToolMeta.status, 'planning');
assert.equal(explicitToolMeta.progress, 10);
assert.equal(explicitToolMeta.phase, 'routing');
assert.equal(explicitToolMeta.interaction_type, 'tool_task');
assert.deepEqual(explicitToolMeta.task_card, { task_id: 'chat-task', status: 'planning' });
assert.equal(
  model.shouldUseRealtimeEventContent(
    { task_id: 'chat-task', streaming: true },
    { task_id: 'chat-task', status: 'planning', interaction_type: 'tool_task' },
    { kind: 'task_status', task_id: 'chat-task' }
  ),
  true,
  'Explicit tool task status text should still update the visible task card'
);

console.log('chatRealtimeEventModel.test.mjs passed');
