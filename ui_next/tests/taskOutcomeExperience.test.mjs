import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const chatPanelSource = readFileSync('src/components/ChatPanel.tsx', 'utf8');
const chatRendererSource = readFileSync('src/components/ChatMessageRenderer.tsx', 'utf8');
const taskCardSource = readFileSync('src/components/chat/task-card/TaskStatusCard.tsx', 'utf8');
const chatUploadsHookSource = readFileSync('src/components/chat/useChatUploads.ts', 'utf8');
const apiSource = readFileSync('src/lib/api.ts', 'utf8');

function loadApiModule() {
  const source = apiSource.replaceAll('import.meta.env', '({})');
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true
    }
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);
}

assert.match(apiSource, /task_outcome\?: Record<string, unknown>/, 'upload/import responses must expose task_outcome');
assert.match(apiSource, /outcome_markdown\?: string/, 'upload/import responses must expose outcome_markdown');
assert.match(apiSource, /result_panel\?: ResultPanel/, 'chat responses must expose result_panel for the right-side result panel');
assert.match(chatPanelSource, /onResultPanel\?\.\(response\.result_panel\)/, 'ChatPanel must forward chat result_panel to the app shell');
assert.match(chatUploadsHookSource, /r\.outcome_markdown/, 'Chat upload hook must show backend task outcome guidance');
assert.match(chatRendererSource, /from ['"]\.\/chat\/task-card['"]/, 'ChatMessageRenderer should consume the extracted task card boundary');
assert.match(taskCardSource, /buildTaskCardPresentation/, 'task cards should use the shared presentation model');
assert.match(taskCardSource, /task-thinking-summary/, 'task cards should expose public thinking summaries');
assert.match(taskCardSource, /公开过程|执行过程|思考/, 'task cards should label public thinking without exposing hidden reasoning');
const apiModule = await loadApiModule();
assert.equal(
  apiModule.formatApiError(403, 'Forbidden', 'platform quota exhausted').message,
  'platform quota exhausted',
  '403 business errors should preserve the backend reason without rewriting them as login expiry'
);
assert.match(
  apiModule.formatApiError(401, 'Unauthorized', 'session expired').message,
  /session expired/,
  '401 errors should still include the backend authentication detail'
);

console.log('taskOutcomeExperience.test.mjs passed');
