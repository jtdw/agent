import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile('src/components/ChatPanel.tsx', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(source.includes('PROMPT_GROUPS'), true);
assert.equal(source.includes('normalizeWorkspaceMentions'), true);
assert.equal(source.includes('MessageSourceBadge'), true);
assert.equal(source.includes('lastFailedPrompt'), true);
assert.equal(source.includes('重试'), true);
assert.equal(source.includes('api.workspaceMentions'), true);
assert.equal(source.includes('检查工作区数据'), true);
assert.equal(source.includes('准备下载数据'), true);
assert.equal(layerPanelSource.includes('if (!user) {'), true);
assert.equal(layerPanelSource.includes('setJobs([]);'), true);

const sendPromptSource = source.match(/const sendPrompt = async[\s\S]*?\n  const send =/)?.[0] || '';
const refreshSessionsSource = source.match(/const refreshSessions = async[\s\S]*?\n  useEffect/)?.[0] || '';
assert.match(refreshSessionsSource, /if \(!userId\) \{[\s\S]*?setSessions\(\[\]\);[\s\S]*?setCurrentSessionId\(''\);[\s\S]*?setMessages\(\[\]\);[\s\S]*?return;/, 'ChatPanel must not load anonymous chat history before login');
assert.match(sendPromptSource, /if \(!userId\) \{[\s\S]*?return;/, 'ChatPanel must not create anonymous chat records before login');
assert.equal(sendPromptSource.includes('mergeStableClientMessageIds(current, normalizeChatMessages(r.messages))'), true);
assert.equal(sendPromptSource.includes('const nextSessionId = r.current_session_id || currentSessionId'), true);
assert.equal(sendPromptSource.includes('setCurrentSessionId(nextSessionId)'), true);
assert.equal(source.includes("meta: { reason: 'download_failed' }"), false, 'ChatPanel should not append a duplicate assistant error when a watched download job fails');
assert.equal(layerPanelSource.includes('failed && job.error_message && !job.failure_diagnostic?.user_message'), true, 'LayerPanel should not render both failure_diagnostic.user_message and error_message for the same failed job');

console.log('chat panel experience tests passed');
