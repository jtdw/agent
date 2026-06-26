import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile('src/components/ChatPanel.tsx', 'utf8');
const chatSessionsHookSource = await readFile('src/components/chat/useChatSessions.ts', 'utf8');
const workspaceMentionsHookSource = await readFile('src/components/chat/useChatWorkspaceMentions.ts', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(source.includes('PROMPT_GROUPS'), true);
assert.match(source, /useChatWorkspaceMentions/, 'ChatPanel should delegate workspace mentions to a focused hook');
assert.doesNotMatch(source, /api\.workspaceMentions/, 'ChatPanel should not own workspace mention API loading after hook extraction');
assert.match(workspaceMentionsHookSource, /export function useChatWorkspaceMentions/, 'useChatWorkspaceMentions hook should be exported');
assert.match(workspaceMentionsHookSource, /export function normalizeWorkspaceMentions/, 'workspace mention normalization should move with the hook');
assert.match(workspaceMentionsHookSource, /api\.workspaceMentions/, 'workspace mention hook should own API loading');
assert.equal(source.includes('MessageSourceBadge'), true);
assert.equal(source.includes('lastFailedPrompt'), true);
assert.equal(source.includes('重试'), true);
assert.equal(source.includes('检查工作区数据'), true);
assert.equal(source.includes('准备下载数据'), true);
assert.equal(layerPanelSource.includes('if (!user) {'), true);
assert.equal(layerPanelSource.includes('setJobs([]);'), true);

const sendPromptSource = source.match(/const sendPrompt = async[\s\S]*?\n  const send =/)?.[0] || '';
const refreshSessionsSource = chatSessionsHookSource.match(/const refreshSessions = useCallback[\s\S]*?\n  useEffect/)?.[0] || '';
assert.match(refreshSessionsSource, /if \(!requestedUserId\) \{[\s\S]*?setSessions\(\[\]\);[\s\S]*?setCurrentSessionId\(''\);[\s\S]*?onMessagesCleared\(\);[\s\S]*?return;/, 'useChatSessions must not load anonymous chat history before login');
const missingUserBranch = refreshSessionsSource.slice(
  refreshSessionsSource.indexOf('if (!requestedUserId) {'),
  refreshSessionsSource.indexOf('let result = await api.chatSessions')
);
assert.match(missingUserBranch, /setSessions\(\[\]\);[\s\S]*?setCurrentSessionId\(''\);[\s\S]*?onMessagesCleared\(\);[\s\S]*?return;/, 'useChatSessions must return before requesting sessions when userId is initially empty');
assert.match(
  missingUserBranch,
  /if \(!requestedUserId\) \{\s*if \(lastKnownUserIdRef\.current\) \{[\s\S]*?lastSuccessfulSessionUserIdRef\.current = '';[\s\S]*?\}\s*setSessions\(\[\]\);[\s\S]*?return;/,
  'useChatSessions must keep previous-user cleanup separate from the unconditional missing-user return'
);
assert.match(sendPromptSource, /if \(!userId\) \{[\s\S]*?return;/, 'ChatPanel must not create anonymous chat records before login');
assert.equal(sendPromptSource.includes('await api.streamChat('), true, 'ChatPanel must send through the streaming chat endpoint');
assert.equal(sendPromptSource.includes('{ ...chatContext, session_id: currentSessionId }'), true, 'Streaming chat must retain session-scoped frontend context');
assert.equal(sendPromptSource.includes('refreshSessions().catch(() => {})'), true, 'Completed streams must reconcile persisted messages without replacing optimistic history');
assert.equal(source.includes("meta: { reason: 'download_failed' }"), false, 'ChatPanel should not append a duplicate assistant error when a watched download job fails');
assert.equal(layerPanelSource.includes('failure_diagnostic'), false, 'LayerPanel should not render raw failure_diagnostic in the management view path');
assert.equal(layerPanelSource.includes('error_message'), false, 'LayerPanel should not render raw error_message in the management view path');
assert.equal(layerPanelSource.includes('jobView(job)?.user_message'), true, 'LayerPanel should render safe management_view.user_message');
assert.equal(layerPanelSource.includes('job.download_url'), false, 'LayerPanel main download management path must not consume raw job.download_url');
assert.match(layerPanelSource, /api\.artifactMetadata/, 'LayerPanel download actions must resolve artifact_id through the artifact resolver');

console.log('chat panel experience tests passed');
