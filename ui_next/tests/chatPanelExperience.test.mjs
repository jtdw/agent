import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile('src/components/ChatPanel.tsx', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(source.includes('PROMPT_GROUPS'), true);
assert.equal(source.includes('WorkspaceQuickStats'), true);
assert.equal(source.includes('MessageSourceBadge'), true);
assert.equal(source.includes('lastFailedPrompt'), true);
assert.equal(source.includes('重试'), true);
assert.equal(source.includes('api.dashboard'), true);
assert.equal(source.includes('数据概览'), true);
assert.equal(source.includes('下载准备'), true);
assert.equal(layerPanelSource.includes('if (!user) {'), true);
assert.equal(layerPanelSource.includes('setJobs([]);'), true);

const sendPromptSource = source.match(/const sendPrompt = async[\s\S]*?\n  const send =/)?.[0] || '';
const refreshSessionsSource = source.match(/const refreshSessions = async[\s\S]*?\n  useEffect/)?.[0] || '';
assert.match(refreshSessionsSource, /if \(!userId\) \{[\s\S]*?setSessions\(\[\]\);[\s\S]*?setCurrentSessionId\(''\);[\s\S]*?setMessages\(\[\]\);[\s\S]*?return;/, 'ChatPanel must not load anonymous chat history before login');
assert.match(sendPromptSource, /if \(!userId\) \{[\s\S]*?return;/, 'ChatPanel must not create anonymous chat records before login');
assert.equal(sendPromptSource.includes('setMessages(normalizeChatMessages(r.messages))'), true);
assert.equal(sendPromptSource.includes('setCurrentSessionId(r.current_session_id || currentSessionId)'), true);

console.log('chat panel experience tests passed');
