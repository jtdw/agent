import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function loadTs(path, transform = (value) => value) {
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
    module: await import(`data:text/javascript;base64,${Buffer.from(transform(result.outputText)).toString('base64')}`)
  };
}

const panel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const workspaceModel = await loadTs('src/components/chat/chatWorkspaceModel.ts');
globalThis.__chatSendModelHashString = workspaceModel.module.hashString;
const { source: modelSource, module: model } = await loadTs(
  'src/components/chat/chatSendModel.ts',
  (source) => source.replace(
    "import { hashString } from './chatWorkspaceModel';",
    'const hashString = globalThis.__chatSendModelHashString;'
  )
);

assert.match(panel, /buildSendPromptDraft/, 'ChatPanel should delegate send-message draft construction to chatSendModel');
assert.match(panel, /buildStreamChatContext/, 'ChatPanel should delegate stream context construction to chatSendModel');
assert.doesNotMatch(panel, /const optimisticUserMessage: ChatMessage =/, 'ChatPanel should not inline optimistic user message construction');
assert.doesNotMatch(panel, /const streamingAssistantMessage: ChatMessage =/, 'ChatPanel should not inline streaming assistant message construction');
assert.match(panel, /await api\.streamChat\(/, 'ChatPanel should still own the streaming API call in this low-risk extraction');

assert.match(modelSource, /export function buildSendPromptDraft/, 'chatSendModel should export buildSendPromptDraft');
assert.match(modelSource, /export function buildStreamChatContext/, 'chatSendModel should export buildStreamChatContext');
assert.match(modelSource, /hashString/, 'chatSendModel should keep stable hash-based ids');

const draft = model.buildSendPromptDraft({
  text: '  run GIS analysis  ',
  realtimeSyncState: 'live',
  now: 123456,
});

assert.equal(draft.text, 'run GIS analysis');
assert.match(draft.taskId, /^chat_123456_/);
assert.equal(draft.optimisticUserMessage.role, 'user');
assert.equal(draft.optimisticUserMessage.content, 'run GIS analysis');
assert.match(draft.optimisticUserMessage.id, /^pending-123456-/);
assert.equal(draft.streamingAssistantMessage.role, 'assistant');
assert.equal(draft.streamingAssistantMessage.content, '');
assert.deepEqual(draft.streamingAssistantMessage.meta, {
  task_id: draft.taskId,
  status: 'planning',
  streaming: true,
  realtime_sync: 'live'
});

const context = model.buildStreamChatContext({ project: 'demo' }, 'session_1');
assert.deepEqual(context, { project: 'demo', session_id: 'session_1' });
assert.deepEqual(model.buildStreamChatContext({ session_id: 'old', project: 'demo' }, 'session_2'), { session_id: 'session_2', project: 'demo' });

console.log('chatSendModelExperience.test.mjs passed');
