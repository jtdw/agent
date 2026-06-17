import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const composer = await readFile('src/components/ChatComposer.tsx', 'utf8');
const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const chatPanel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const api = await readFile('src/lib/api.ts', 'utf8');
const productConsole = await readFile('src/components/ProductConsole.tsx', 'utf8');

assert.match(api, /export type WorkspaceMention[\s\S]*mention\?/, 'WorkspaceMention must support @ mention tokens');
assert.match(api, /chatModels/, 'api.ts must expose chat model state');
assert.match(api, /selectChatModel/, 'api.ts must expose model selection');
assert.match(api, /workspaceMentions/, 'api.ts must expose workspace mention data');

assert.match(composer, /export function ChatComposer/, 'ChatComposer must be exported');
assert.match(composer, /data-testid="chat-mention-menu"/, 'ChatComposer must show @ mention menu');
assert.match(composer, /onDrop/, 'ChatComposer must support drag-and-drop uploads');
assert.match(composer, /data-testid="chat-stop"/, 'ChatComposer must support stopping a running chat request');
assert.match(composer, /data-testid="chat-voice"/, 'ChatComposer must expose voice input');

assert.match(renderer, /ReactMarkdown/, 'ChatMessageRenderer must render Markdown');
assert.match(renderer, /artifact-download-list/, 'ChatMessageRenderer must render artifact cards');
assert.match(renderer, /gscloud-login-required/, 'ChatMessageRenderer must render GSCloud login-required action');

assert.match(chatPanel, /export function ChatWorkspace/, 'ChatPanel must expose page and floating chat workspace');
assert.match(chatPanel, /<ChatComposer/, 'ChatPanel must use ChatComposer');
assert.match(chatPanel, /<ChatMessageRenderer/, 'ChatPanel must use ChatMessageRenderer');
assert.match(chatPanel, /chatModels/, 'ChatPanel must load and render model selection');
assert.match(chatPanel, /workspaceMentions/, 'ChatPanel must load workspace @ mentions');
assert.match(chatPanel, /data-testid="chat-session-list"/, 'ChatPanel must render session/data partition area');
assert.match(chatPanel, /AbortController/, 'ChatPanel must support cooperative stop');

assert.match(productConsole, /activeTab === 'chat'/, 'ProductConsole must have a dedicated chat layout branch');
assert.match(productConsole, /<ChatWorkspace/, 'ProductConsole chat tab must embed ChatWorkspace');

console.log('chatUpgradeComponents.test.mjs passed');
