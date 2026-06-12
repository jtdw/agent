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

const content = await loadTs('src/components/chatMessageContent.ts');
const chatPanelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');

assert.equal(content.assistantReplyContent('  已完成分析。  '), '已完成分析。');
assert.match(content.assistantReplyContent(''), /没有返回可显示内容/);
assert.match(content.assistantReplyContent(null), /没有返回可显示内容/);
assert.match(content.assistantErrorContent(new Error('后端连接失败')), /后端连接失败/);
assert.match(content.assistantErrorContent('timeout'), /timeout/);
assert.match(content.normalizeChatMessages([{ role: 'assistant', content: '' }])[0].content, /没有返回可显示内容/);
assert.match(
  content.normalizeChatMessages([{ role: 'assistant', content: '???????????????????????????????? XGBoost ??????????????' }])[0].content,
  /无法显示|鏃犳硶鏄剧ず/,
  'Unreadable question-mark history should be replaced by a readable fallback'
);
assert.equal(content.normalizeChatMessages([{ role: 'user', content: '' }])[0].content, '');
assert.equal(chatPanelSource.includes('assistantReplyContent'), true);
assert.equal(chatPanelSource.includes('assistantErrorContent'), true);
assert.equal(chatPanelSource.includes('normalizeChatMessages'), true);

console.log('chat message content tests passed');
