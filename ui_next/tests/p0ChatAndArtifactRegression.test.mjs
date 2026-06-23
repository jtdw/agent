import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8');
const chatPanel = readFileSync(resolve(root, 'src/components/ChatPanel.tsx'), 'utf8');
const artifactCard = readFileSync(resolve(root, 'src/components/ArtifactDownloadCard.tsx'), 'utf8');
const api = readFileSync(resolve(root, 'src/lib/api.ts'), 'utf8');

assert.match(app, /readStoredUser/, 'App must restore the stored authenticated user before chat session loading depends on user_id');
assert.match(app, /api\.me\(\)/, 'App must validate the cookie-backed auth session on startup');
assert.match(app, /writeStoredUser/, 'App must refresh stored auth after session validation');
assert.doesNotMatch(app, /\.catch\(\(\) => \{[\s\S]*?clearStoredAuth\(\);[\s\S]*?setUser\(null\);[\s\S]*?\}\);/s, 'App must not clear restored user on transient auth API failures');
assert.doesNotMatch(readFileSync(resolve(root, 'src/components/AuthPanel.tsx'), 'utf8'), /\.catch\(\(\) => \{[\s\S]*?clearStoredAuth\(\);[\s\S]*?setUser\(null\);[\s\S]*?\}\);/s, 'AuthPanel must not clear restored user on transient auth API failures');
assert.match(chatPanel, /function mergeServerMessages/, 'ChatPanel must merge server messages through a guarded helper');
assert.match(chatPanel, /chat_load_failed/, 'ChatPanel must preserve visible messages when initial or refresh loading fails');
assert.match(chatPanel, /sessionRefreshSeqRef/, 'ChatPanel must ignore stale session refresh responses');
assert.match(chatPanel, /lastKnownUserIdRef/, 'ChatPanel must not clear sessions during initial auth restoration');
assert.match(chatPanel, /latestUserIdRef\.current !== requestedUserId/, 'ChatPanel must avoid applying session responses for another user');
assert.doesNotMatch(chatPanel, /refreshSessions\(\)\.catch\(\(\) => \{\s*setSessions\(\[\]\);\s*setCurrentSessionId\(''\);\s*setMessages\(\[\]\);/s, 'refreshSessions failure must not clear the active message list');
assert.match(chatPanel, /window\.confirm\([^)]*删除当前对话/s, 'Deleting a conversation must require explicit user confirmation');
assert.match(chatPanel, /setMessages\(\(current\) => mergeServerMessages\(current, normalizeChatMessages\(r\.messages\)\)\)/, 'Session refresh must merge, not blindly replace, server messages');

assert.match(api, /downloadArtifactById/, 'api.ts must expose artifact-id based download resolver');
assert.match(api, /\/api\/artifacts\/\$\{encodeURIComponent\(artifact_id\)\}\/download/, 'artifact download must use the backend artifact resolver endpoint');
assert.match(artifactCard, /api\.downloadArtifactById\(resolved\.artifact_id/, 'ArtifactDownloadCard must download by artifact_id');
assert.doesNotMatch(artifactCard, /downloadNative\(resolvedDownloadUrl|downloadAuthenticated\(resolvedDownloadUrl/, 'ArtifactDownloadCard must not download from stale raw download_url');
assert.match(artifactCard, /文件已清理、无访问权限或下载链接已失效/, 'ArtifactDownloadCard must show a Chinese resolver failure message');

console.log('p0ChatAndArtifactRegression.test.mjs passed');
