import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile('src/components/ChatPanel.tsx', 'utf8');
const composerSource = await readFile('src/components/ChatComposer.tsx', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(source.includes('PROMPT_GROUPS'), true);
assert.equal(source.includes('WorkspaceQuickStats'), false, 'Chat must not duplicate workspace statistics owned by other product surfaces');
assert.equal(source.includes('MessageSourceBadge'), true);
assert.equal(source.includes('lastFailedPrompt'), true);
assert.equal(source.includes('重试'), true);
assert.equal(source.includes('api.dashboard'), false, 'Chat must not fetch dashboard statistics it no longer renders');
assert.equal(source.includes('数据概览'), false, 'Chat must not render a persistent data overview card');
assert.equal(source.includes('准备下载数据'), true);
assert.equal(layerPanelSource.includes('if (!user) {'), true);
assert.equal(layerPanelSource.includes('setJobs([]);'), true);
assert.match(source, /export function ChatWorkspace/, 'ChatPanel module must export a reusable ChatWorkspace');
assert.match(source, /mode = 'floating'/, 'ChatWorkspace must default to floating mode for the existing panel');
assert.match(source, /mode="floating"/, 'ChatPanel wrapper must render ChatWorkspace in floating mode');
assert.match(source, /mode === 'page'/, 'ChatWorkspace must support a full page mode');
assert.match(source, /data-testid="chat-page-workspace"/, 'ChatWorkspace page mode must expose a stable page workspace hook');
assert.match(source, /data-testid="chat-session-list"/, 'Shared chat workspace must expose a session list area');
assert.match(source, /data-testid="chat-new-session"/, 'The session rail must expose a prominent new conversation action');
assert.match(source, /data-testid="chat-conversation-header"/, 'The main pane must expose a compact conversation header');
assert.match(source, /data-testid="chat-model-selector"/, 'The conversation header must expose a model selector');
assert.match(source, /data-testid="floating-chat-toolbar"/, 'Floating chat must use a dedicated compact toolbar instead of the full page header controls');
assert.match(source, /data-testid="floating-chat-delete"/, 'Floating chat must expose a visible delete/clear current conversation action');
assert.doesNotMatch(composerSource, /data-testid="chat-language-selector"/, 'Chat composer must not expose language selection in the input bar');
assert.match(composerSource, /data-testid="chat-voice"/, 'Chat composer must expose a voice input control');
assert.match(source, /api\.chatModels\(userId, currentSessionId\)/, 'Model options must reload for the current conversation');
assert.match(source, /api\.selectChatModel\(model, userId, currentSessionId\)/, 'Model selection must be persisted through the chat model API');
assert.match(source, /disabled=\{thinking \|\| modelLoading\}/, 'Conversation switching must be disabled while a model change is in flight');
assert.doesNotMatch(source, /appendSystem\([^)]*模型/, 'Changing the chat model must not append a system message');
assert.match(source, /data-testid="chat-empty-state"/, 'The empty conversation must expose a focused task starter state');
assert.match(source, /chat-primary-action/, 'Chat must use the approved primary button treatment');
assert.match(source, /chat-secondary-action/, 'Chat must use the approved secondary button treatment');
assert.match(source, /chat-prompt-card/, 'Task starters must use the approved prompt card treatment');
assert.doesNotMatch(source, /<AuthPanel user=\{user\} setUser=\{setUser\} \/>/, 'Chat must not duplicate the global account panel');
assert.doesNotMatch(source, />智能助手</, 'Chat must not duplicate the assistant title already represented by the page');
assert.doesNotMatch(source, />GIS Agent</, 'Chat must not duplicate product branding inside the conversation workspace');
assert.doesNotMatch(
  source,
  /rounded-2xl border border-cyan-glow\/50[\s\S]*?repeat:\s*Infinity/,
  'Shared chat header must not run an unconditional infinite pulse because it flickers in both floating and page modes'
);

const sendPromptSource = source.match(/const sendPrompt = async[\s\S]*?\n  const send =/)?.[0] || '';
const refreshSessionsSource = source.match(/const refreshSessions = async[\s\S]*?\n  useEffect/)?.[0] || '';
assert.match(refreshSessionsSource, /if \(!userId\) \{[\s\S]*?setSessions\(\[\]\);[\s\S]*?setCurrentSessionId\(''\);[\s\S]*?setMessages\(\[\]\);[\s\S]*?return;/, 'ChatPanel must not load anonymous chat history before login');
assert.match(sendPromptSource, /if \(!userId\) \{[\s\S]*?return;/, 'ChatPanel must not create anonymous chat records before login');
assert.match(sendPromptSource, /setMessages\(\(current\) => mergeStableClientMessageIds\(current, normalizeChatMessages\(r\.messages\)\)\)/);
assert.equal(sendPromptSource.includes('const nextSessionId = r.current_session_id || currentSessionId'), true);
assert.equal(sendPromptSource.includes('setCurrentSessionId(nextSessionId)'), true);
assert.match(source, /mergeStableClientMessageIds/, 'ChatPanel must preserve optimistic message keys when server messages return');
assert.match(source, /id:\s*`pending-\$\{Date\.now\(\)\}-\$\{hashString\(text\)\}`/, 'Optimistic user messages must carry a stable client id');
assert.match(source, /if \(message\.id\) return `message-\$\{message\.id\}`;[\s\S]*?if \(message\.message_id\)/, 'ChatPanel message keys must prefer stable client ids before persisted ids');

console.log('chat panel experience tests passed');
