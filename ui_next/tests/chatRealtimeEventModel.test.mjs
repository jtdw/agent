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
    interaction_type: 'chat_answer',
    reason: 'chat_only_direct_answer'
  },
  { kind: 'model_complete', task_id: 'chat-1' }
);
assert.equal(cleanChatMeta.interaction_type, 'chat_answer');
assert.equal(cleanChatMeta.mode, 'answer_only');
assert.equal(cleanChatMeta.status, 'succeeded');
assert.equal(cleanChatMeta.task_card, undefined);
assert.equal(cleanChatMeta.management_view, undefined);
assert.equal(cleanChatMeta.download_management_view, undefined);
assert.equal(cleanChatMeta.action_required, undefined);

console.log('chatRealtimeEventModel.test.mjs passed');
