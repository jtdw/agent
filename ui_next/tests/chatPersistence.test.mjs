import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const apiSource = readFileSync(resolve(root, 'src/lib/api.ts'), 'utf8');
const chatPanelSource = readFileSync(resolve(root, 'src/components/ChatPanel.tsx'), 'utf8');

assert.match(apiSource, /clearChatSession/, 'api.ts must expose a persistent clearChatSession call');
assert.match(apiSource, /\/api\/chat\/sessions\/clear/, 'clearChatSession must call the backend clear endpoint');
assert.match(chatPanelSource, /api\.clearChatSession/, 'ChatPanel delete action must clear the current session when it is the only session');
assert.doesNotMatch(chatPanelSource, /sessions\.length\s*<=\s*1/, 'delete/clear button must remain usable for the last session');

console.log('chatPersistence.test.mjs passed');
