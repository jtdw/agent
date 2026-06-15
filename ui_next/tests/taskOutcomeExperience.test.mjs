import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const chatPanelSource = readFileSync('src/components/ChatPanel.tsx', 'utf8');
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
assert.match(apiSource, /upload_summaries\?: UploadSummary\[\]/, 'upload/import responses must expose compact upload summaries');
assert.match(apiSource, /result_panel\?: ResultPanel/, 'chat responses must expose result_panel for the right-side result panel');
assert.match(chatPanelSource, /onResultPanel\?\.\(r\.result_panel\)/, 'ChatPanel must forward chat result_panel to the app shell');
assert.match(chatPanelSource, /r\.outcome_markdown/, 'ChatPanel upload flow must show backend task outcome guidance');
assert.match(chatPanelSource, /UploadResultCard/, 'ChatPanel upload flow must render compact upload cards');
assert.doesNotMatch(chatPanelSource, /appendSystem\(`已上传并载入 \$\{r\.count\}/, 'Upload flow must not append long raw system text as the primary UI');
assert.doesNotMatch(chatPanelSource, /r\.messages\.slice\(0,\s*2\)\.join/, 'Upload flow must not append raw backend upload messages after the compact outcome');

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
