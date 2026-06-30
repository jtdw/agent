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
  return import(`data:text/javascript;base64,${Buffer.from(transform(result.outputText)).toString('base64')}`);
}

const chatContext = await loadTs('src/lib/chatContext.ts');
const workspaceModel = await loadTs('src/components/chat/chatWorkspaceModel.ts');
globalThis.__frontendContextHashString = workspaceModel.hashString;
const chatSendModel = await loadTs(
  'src/components/chat/chatSendModel.ts',
  (source) => source.replace(
    "import { hashString } from './chatWorkspaceModel';",
    'const hashString = globalThis.__frontendContextHashString;'
  )
);
const apiSource = await readFile('src/lib/api.ts', 'utf8');
const appSource = await readFile('src/App.tsx', 'utf8');
const chatPanelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');
const promptStreamActionHookSource = await readFile('src/components/chat/useChatPromptStreamAction.ts', 'utf8');
const mapStageSource = await readFile('src/components/MapStage.tsx', 'utf8');
const analysisPanelSource = await readFile('src/components/AnalysisPanel.tsx', 'utf8');

const payload = chatContext.sanitizeChatContextPayload({
  session_id: 'session_1',
  selected_feature_properties: {
    name: 'A'.repeat(300),
    token: 'secret',
    raw_content: 'x'.repeat(1000),
    safe: 1,
    file: 'not allowed',
    html: '<b>bad</b>'
  },
  selected_map_bounds: [100, 20, 101, 21]
});

assert.equal(payload.session_id, 'session_1');
assert.deepEqual(payload.selected_map_bounds, [100, 20, 101, 21]);
assert.equal(payload.selected_feature_properties.safe, 1);
assert.equal(payload.selected_feature_properties.name.length, 200);
assert.equal('token' in payload.selected_feature_properties, false);
assert.equal('raw_content' in payload.selected_feature_properties, false);
assert.equal('file' in payload.selected_feature_properties, false);
assert.equal('html' in payload.selected_feature_properties, false);

assert.match(apiSource, /frontend_context/, 'api.ask must send frontend_context');
assert.match(apiSource, /ChatContextPayload/, 'api.ask should type frontend context payload');
assert.match(chatPanelSource, /chatContext/, 'ChatPanel must accept chatContext');
assert.match(promptStreamActionHookSource, /buildStreamChatContext\(chatContext,\s*currentSessionId\)/, 'Prompt stream hook must pass session-scoped context to streaming chat');
assert.deepEqual(chatSendModel.buildStreamChatContext({ session_id: 'stale', selected_artifact_id: 'a1' }, 'session_2'), { session_id: 'session_2', selected_artifact_id: 'a1' });
assert.match(appSource, /chatContext/, 'App must own chat context state');
assert.match(appSource, /setChatContext/, 'App must update chat context');
assert.match(mapStageSource, /onChatContextChange/, 'MapStage must report selected map context');
assert.match(mapStageSource, /selected_feature_properties/, 'MapStage must report clicked feature properties');
assert.match(mapStageSource, /selected_map_bounds/, 'MapStage must report current bounds');
assert.match(analysisPanelSource, /onChatContextChange/, 'AnalysisPanel must report selected result context');
assert.match(analysisPanelSource, /selected_artifact_id/, 'AnalysisPanel must report selected artifacts');
assert.match(analysisPanelSource, /selected_artifact_id:\s*item\.artifactId\s*\|\|/, 'AnalysisPanel must prefer backend artifact_id over display labels');
assert.match(analysisPanelSource, /selected_model_result_id/, 'AnalysisPanel must report selected model result');
assert.match(analysisPanelSource, /view\.bestModel\?\.modelResultId/, 'AnalysisPanel must send backend model_result_id');
assert.doesNotMatch(analysisPanelSource, /selected_model_result_id:\s*view\.bestModel\?\.name/, 'AnalysisPanel must not use display model name as selected_model_result_id');
assert.match(analysisPanelSource, /sessionId\?:\s*string/, 'AnalysisPanel must accept a session id for scoped result loading');
assert.match(analysisPanelSource, /api\.dashboard\(userId,\s*sessionId\)/, 'AnalysisPanel must load dashboard results in the current session scope');
assert.match(appSource, /<AnalysisPanel userId=\{user\?\.user_id \|\| ''\} sessionId=\{currentSessionId\}/, 'App must pass the current session id into AnalysisPanel');

console.log('frontend context payload tests passed');
