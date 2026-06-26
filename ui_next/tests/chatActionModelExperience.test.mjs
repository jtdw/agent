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

const panelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');
const editingHookSource = await readFile('src/components/chat/useChatEditing.ts', 'utf8');
const { source: modelSource, module: model } = await loadTs('src/components/chat/chatActionModel.ts');

assert.match(editingHookSource, /buildRetryEditedMessageDraft/, 'useChatEditing should delegate edited-message retry draft construction');
assert.doesNotMatch(panelSource, /buildRetryEditedMessageDraft/, 'ChatPanel should not own edited-message retry draft construction after hook extraction');
assert.match(panelSource, /THESIS_WORKFLOW_PROMPT/, 'ChatPanel should use the shared thesis workflow prompt');
assert.doesNotMatch(panelSource, /const text = editText\.trim\(\)/, 'ChatPanel should not inline retry edit text normalization');
assert.doesNotMatch(panelSource, /const prompt = '一键检查并运行闪电河流域土壤水分融合论文流程。'/, 'ChatPanel should not inline the thesis workflow prompt');

assert.match(modelSource, /export function buildRetryEditedMessageDraft/, 'chatActionModel should export buildRetryEditedMessageDraft');
assert.match(modelSource, /export const THESIS_WORKFLOW_PROMPT/, 'chatActionModel should export the thesis workflow prompt');

assert.deepEqual(model.buildRetryEditedMessageDraft(42, '  重新分析当前图层  '), {
  messageId: 42,
  text: '重新分析当前图层',
});
assert.equal(model.buildRetryEditedMessageDraft(null, '重新分析'), null);
assert.equal(model.buildRetryEditedMessageDraft(42, '   '), null);
assert.equal(model.THESIS_WORKFLOW_PROMPT, '一键检查并运行闪电河流域土壤水分融合论文流程。');

console.log('chatActionModelExperience.test.mjs passed');
