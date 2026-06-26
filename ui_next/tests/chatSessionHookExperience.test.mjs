import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const panel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const hook = await readFile('src/components/chat/useChatSessions.ts', 'utf8');

assert.match(panel, /useChatSessions/, 'ChatPanel should delegate session loading state to useChatSessions');
assert.doesNotMatch(panel, /api\.chatSessions/, 'ChatPanel should not own initial session list API calls');
assert.doesNotMatch(panel, /const refreshSessions = async/, 'ChatPanel should not own the initial session refresh implementation');
assert.doesNotMatch(panel, /useState<ChatSession\[\]>/, 'ChatPanel should not own raw chat session collection state');

assert.match(hook, /export function useChatSessions/, 'useChatSessions hook should be exported');
assert.match(hook, /api\.chatSessions/, 'useChatSessions should load available sessions');
assert.match(hook, /visibleSessions/, 'useChatSessions should expose de-duplicated visibleSessions');
assert.match(hook, /currentSession/, 'useChatSessions should expose currentSession for header rendering');
assert.match(hook, /lastSuccessfulSessionUserIdRef/, 'useChatSessions should preserve stale empty-session protection');
assert.match(hook, /sessionRefreshSeqRef/, 'useChatSessions should guard against stale refresh races');
assert.match(hook, /onMessagesRefreshed/, 'useChatSessions should delegate message merge policy back to ChatPanel');
assert.match(hook, /onSessionChange/, 'useChatSessions should keep external session-change notifications');

console.log('chatSessionHookExperience.test.mjs passed');
