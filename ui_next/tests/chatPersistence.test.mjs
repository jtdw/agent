import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const apiSource = readFileSync(resolve(root, 'src/lib/api.ts'), 'utf8');
const chatPanelSource = readFileSync(resolve(root, 'src/components/ChatPanel.tsx'), 'utf8');
const chatSessionsHookSource = readFileSync(resolve(root, 'src/components/chat/useChatSessions.ts'), 'utf8');
const deleteSessionActionHookSource = readFileSync(resolve(root, 'src/components/chat/useChatDeleteSessionAction.ts'), 'utf8');

assert.match(apiSource, /clearChatSession/, 'api.ts must expose a persistent clearChatSession call');
assert.match(apiSource, /\/api\/chat\/sessions\/clear/, 'clearChatSession must call the backend clear endpoint');
assert.match(deleteSessionActionHookSource, /api\.clearChatSession/, 'Delete session action must clear the current session when it is the only session');
assert.doesNotMatch(chatPanelSource, /sessions\.length\s*<=\s*1/, 'delete/clear button must remain usable for the last session');
assert.match(apiSource, /message_count\?: number/, 'ChatSession must expose backend message counts for stable recent-session rendering');
assert.match(chatSessionsHookSource, /lastSuccessfulSessionUserIdRef/, 'useChatSessions must remember the last user with valid session data');
assert.match(chatSessionsHookSource, /nextSessions\.length === 0 && lastSuccessfulSessionUserIdRef\.current === requestedUserId/, 'useChatSessions must not let an empty refresh overwrite known sessions for the same user');

console.log('chatPersistence.test.mjs passed');
