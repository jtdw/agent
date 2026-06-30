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
const messageList = await readFile('src/components/chat/ChatMessageList.tsx', 'utf8');
const promptStreamActionHook = await readFile('src/components/chat/useChatPromptStreamAction.ts', 'utf8');
const workspaceModel = await loadTs('src/components/chat/chatWorkspaceModel.ts');
globalThis.__chatSendModelHashString = workspaceModel.module.hashString;
const { source: modelSource, module: model } = await loadTs(
  'src/components/chat/chatSendModel.ts',
  (source) => source.replace(
    "import { hashString } from './chatWorkspaceModel';",
    'const hashString = globalThis.__chatSendModelHashString;'
  )
);

assert.match(promptStreamActionHook, /buildSendPromptDraft/, 'Prompt stream hook should delegate send-message draft construction to chatSendModel');
assert.match(promptStreamActionHook, /buildStreamChatContext/, 'Prompt stream hook should delegate stream context construction to chatSendModel');
assert.doesNotMatch(panel, /const optimisticUserMessage: ChatMessage =/, 'ChatPanel should not inline optimistic user message construction');
assert.doesNotMatch(panel, /const streamingAssistantMessage: ChatMessage =/, 'ChatPanel should not inline streaming assistant message construction');
assert.match(promptStreamActionHook, /await api\.streamChat\(/, 'Prompt stream hook should own the streaming API call after extraction');
assert.match(messageList, /m\.meta\?\.streaming\s*\?\s*m\.content\s*:\s*assistantReplyContent\(m\.content\)/, 'Streaming assistant placeholders must render as live placeholders instead of the empty-reply fallback');

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
  streaming: true,
  realtime_sync: 'live'
});
assert.equal(
  Object.prototype.hasOwnProperty.call(draft.streamingAssistantMessage.meta, 'status'),
  false,
  'Chat answer placeholders must not advertise planning status before the backend classifies the turn'
);

const downloadDraft = model.buildSendPromptDraft({
  text: '帮我下载成都市30m的dem数据',
  realtimeSyncState: 'live',
  interactionMode: 'tool_enabled',
  now: 123457,
});
assert.equal(downloadDraft.streamingAssistantMessage.meta.interaction_type, 'tool_task');
assert.equal(downloadDraft.streamingAssistantMessage.meta.status, 'planning');
assert.equal(downloadDraft.streamingAssistantMessage.meta.task_card.task_id, downloadDraft.taskId);
assert.equal(downloadDraft.streamingAssistantMessage.meta.task_card.status, 'planning');

const chatOnlyDownloadDraft = model.buildSendPromptDraft({
  text: '帮我下载成都市30m的dem数据',
  realtimeSyncState: 'live',
  interactionMode: 'chat_only',
  now: 123458,
});
assert.equal(chatOnlyDownloadDraft.streamingAssistantMessage.meta.task_card, undefined);
assert.equal(chatOnlyDownloadDraft.streamingAssistantMessage.meta.interaction_type, undefined);

const context = model.buildStreamChatContext({ project: 'demo' }, 'session_1');
assert.deepEqual(context, { project: 'demo', session_id: 'session_1' });
assert.deepEqual(model.buildStreamChatContext({ session_id: 'old', project: 'demo' }, 'session_2'), { session_id: 'session_2', project: 'demo' });

console.log('chatSendModelExperience.test.mjs passed');
