import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8');
const chatPanel = readFileSync(resolve(root, 'src/components/ChatPanel.tsx'), 'utf8');
const chatSessionsHook = readFileSync(resolve(root, 'src/components/chat/useChatSessions.ts'), 'utf8');
const deleteSessionActionHook = readFileSync(resolve(root, 'src/components/chat/useChatDeleteSessionAction.ts'), 'utf8');
const artifactCard = readFileSync(resolve(root, 'src/components/ArtifactDownloadCard.tsx'), 'utf8');
const api = readFileSync(resolve(root, 'src/lib/api.ts'), 'utf8');

assert.match(app, /readStoredUser/, 'App must restore the stored authenticated user before chat session loading depends on user_id');
assert.match(app, /api\.me\(\)/, 'App must validate the cookie-backed auth session on startup');
assert.match(app, /writeStoredUser/, 'App must refresh stored auth after session validation');
assert.doesNotMatch(app, /\.catch\(\(\) => \{[\s\S]*?clearStoredAuth\(\);[\s\S]*?setUser\(null\);[\s\S]*?\}\);/s, 'App must not clear restored user on transient auth API failures');
assert.doesNotMatch(readFileSync(resolve(root, 'src/components/AuthPanel.tsx'), 'utf8'), /\.catch\(\(\) => \{[\s\S]*?clearStoredAuth\(\);[\s\S]*?setUser\(null\);[\s\S]*?\}\);/s, 'AuthPanel must not clear restored user on transient auth API failures');
assert.match(chatPanel, /function mergeServerMessages/, 'ChatPanel must merge server messages through a guarded helper');
assert.match(chatPanel, /chat_load_failed/, 'ChatPanel must preserve visible messages when initial or refresh loading fails');
assert.match(chatSessionsHook, /sessionRefreshSeqRef/, 'useChatSessions must ignore stale session refresh responses');
assert.match(chatSessionsHook, /lastKnownUserIdRef/, 'useChatSessions must not clear sessions during initial auth restoration');
assert.match(chatSessionsHook, /latestUserIdRef\.current !== requestedUserId/, 'useChatSessions must avoid applying session responses for another user');
assert.doesNotMatch(chatSessionsHook, /refreshSessions\(\)\.catch\(\(\) => \{\s*setSessions\(\[\]\);\s*setCurrentSessionId\(''\);\s*onMessagesCleared\(\);/s, 'refreshSessions failure must not clear the active message list');
assert.match(deleteSessionActionHook, /window\.confirm\(/, 'Deleting a conversation must require explicit user confirmation');
assert.match(chatPanel, /setMessages\(\(current\) => mergeServerMessages\(current, normalizeChatMessages\(incoming\)\)\)/, 'Session refresh must merge, not blindly replace, server messages');
assert.match(chatSessionsHook, /onMessagesRefreshed\(result\.messages\)/, 'useChatSessions must pass refreshed messages back to ChatPanel merge policy');

assert.match(api, /downloadArtifactById/, 'api.ts must expose artifact-id based download resolver');
assert.match(api, /\/api\/artifacts\/\$\{encodeURIComponent\(artifact_id\)\}\/download/, 'artifact download must use the backend artifact resolver endpoint');
assert.match(artifactCard, /api\.downloadArtifactById\(resolved\.artifact_id/, 'ArtifactDownloadCard must download by artifact_id');
assert.doesNotMatch(artifactCard, /downloadNative\(resolvedDownloadUrl|downloadAuthenticated\(resolvedDownloadUrl/, 'ArtifactDownloadCard must not download from stale raw download_url');
assert.doesNotMatch(artifactCard, /resolved\.download_url\s*\|\|/, 'ArtifactDownloadCard image previews must not use stale raw download_url before artifact metadata resolves');
assert.match(artifactCard, /resolvedArtifact\?\.download_url/, 'ArtifactDownloadCard image previews must use resolver metadata URLs');
assert.match(artifactCard, /文件已清理、无访问权限或下载链接已失效/, 'ArtifactDownloadCard must show a Chinese resolver failure message');

console.log('p0ChatAndArtifactRegression.test.mjs passed');
