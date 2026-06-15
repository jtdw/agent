import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const apiSource = readFileSync(resolve(root, 'src/lib/api.ts'), 'utf8');
const chatPanelSource = readFileSync(resolve(root, 'src/components/ChatPanel.tsx'), 'utf8');

assert.match(apiSource, /clearChatSession/, 'api.ts must expose a persistent clearChatSession call');
assert.match(apiSource, /\/api\/chat\/sessions\/clear/, 'clearChatSession must call the backend clear endpoint');
assert.match(apiSource, /async chatModels\(/, 'api.ts must expose chat model options');
assert.match(apiSource, /\/api\/chat\/models/, 'chatModels must call the backend model endpoint');
assert.match(apiSource, /async selectChatModel\(/, 'api.ts must expose per-conversation model selection');
assert.match(apiSource, /\/api\/chat\/models\/select/, 'selectChatModel must call the backend selection endpoint');
assert.match(chatPanelSource, /api\.clearChatSession/, 'ChatPanel delete action must clear the current session when it is the only session');
assert.doesNotMatch(chatPanelSource, /sessions\.length\s*<=\s*1/, 'delete/clear button must remain usable for the last session');

console.log('chatPersistence.test.mjs passed');
