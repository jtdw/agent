import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile('src/components/ChatPanel.tsx', 'utf8');
const chatSessionsHookSource = await readFile('src/components/chat/useChatSessions.ts', 'utf8');
const workspaceMentionsHookSource = await readFile('src/components/chat/useChatWorkspaceMentions.ts', 'utf8');
const resizeHookSource = await readFile('src/components/chat/useChatPanelResize.ts', 'utf8');
const autoScrollHookSource = await readFile('src/components/chat/useChatAutoScroll.ts', 'utf8');
const externalPromptHookSource = await readFile('src/components/chat/useChatExternalPrompt.ts', 'utf8');
const editingHookSource = await readFile('src/components/chat/useChatEditing.ts', 'utf8');
const thesisWorkflowHookSource = await readFile('src/components/chat/useChatThesisWorkflow.ts', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(source.includes('PROMPT_GROUPS'), true);
assert.match(source, /useChatWorkspaceMentions/, 'ChatPanel should delegate workspace mentions to a focused hook');
assert.doesNotMatch(source, /api\.workspaceMentions/, 'ChatPanel should not own workspace mention API loading after hook extraction');
assert.match(workspaceMentionsHookSource, /export function useChatWorkspaceMentions/, 'useChatWorkspaceMentions hook should be exported');
assert.match(workspaceMentionsHookSource, /export function normalizeWorkspaceMentions/, 'workspace mention normalization should move with the hook');
assert.match(workspaceMentionsHookSource, /api\.workspaceMentions/, 'workspace mention hook should own API loading');
assert.match(source, /useChatPanelResize/, 'ChatPanel should delegate floating panel resize behavior to a focused hook');
assert.doesNotMatch(source, /const dragHandle = useMemo/, 'ChatPanel should not own pointer resize handlers inline');
assert.match(resizeHookSource, /export function useChatPanelResize/, 'useChatPanelResize hook should be exported');
assert.match(resizeHookSource, /initialWidth = 430/, 'resize hook should preserve the existing default floating width');
assert.match(resizeHookSource, /minWidth = 360/, 'resize hook should preserve the existing minimum floating width');
assert.match(resizeHookSource, /maxWidth = 680/, 'resize hook should preserve the existing maximum floating width');
assert.match(resizeHookSource, /window\.addEventListener\('pointermove'/, 'resize hook should own pointermove subscription');
assert.match(source, /useChatAutoScroll/, 'ChatPanel should delegate chat list auto-scroll behavior to a focused hook');
assert.doesNotMatch(source, /stickToBottomRef/, 'ChatPanel should not own sticky-bottom scroll state inline');
assert.match(autoScrollHookSource, /export function useChatAutoScroll/, 'useChatAutoScroll hook should be exported');
assert.match(autoScrollHookSource, /scrollHeight - target\.scrollTop - target\.clientHeight < 96/, 'auto-scroll hook should preserve the existing sticky threshold');
assert.match(autoScrollHookSource, /scrollTo\(\{ top: listRef\.current\.scrollHeight, behavior: 'smooth' \}\)/, 'auto-scroll hook should keep smooth scroll-to-bottom behavior');
assert.match(source, /useChatExternalPrompt/, 'ChatPanel should delegate external prompt dispatch to a focused hook');
assert.doesNotMatch(source, /if \(externalPrompt\?\.prompt\) sendPrompt\(externalPrompt\.prompt\)/, 'ChatPanel should not own external prompt effect inline');
assert.match(externalPromptHookSource, /export function useChatExternalPrompt/, 'useChatExternalPrompt hook should be exported');
assert.match(externalPromptHookSource, /externalPrompt\?\.prompt/, 'external prompt hook should preserve prompt presence guard');
assert.match(externalPromptHookSource, /sendPromptRef\.current\(externalPrompt\.prompt\)/, 'external prompt hook should send the provided prompt through the current sender');
assert.match(externalPromptHookSource, /sendPromptRef\.current = sendPrompt/, 'external prompt hook should keep the latest sender without widening dispatch triggers');
assert.match(externalPromptHookSource, /\[externalPrompt\?\.id\]/, 'external prompt hook should retain id-scoped triggering');
assert.match(source, /useChatEditing/, 'ChatPanel should delegate edit-and-regenerate state to a focused hook');
assert.doesNotMatch(source, /const \[editingId, setEditingId\]/, 'ChatPanel should not own editing id state inline');
assert.doesNotMatch(source, /const retryEditedMessage = async/, 'ChatPanel should not own edited-message retry flow inline');
assert.match(editingHookSource, /export function useChatEditing/, 'useChatEditing hook should be exported');
assert.match(editingHookSource, /buildRetryEditedMessageDraft/, 'useChatEditing should preserve retry draft validation');
assert.match(editingHookSource, /api\.retryMessage\(draft\.messageId, draft\.text, userId, currentSessionId\)/, 'useChatEditing should preserve session-scoped retry API call');
assert.match(editingHookSource, /onRetryComplete\(response\)/, 'useChatEditing should hand retry responses back to ChatPanel for existing merge/session reconciliation');
assert.match(source, /mergeServerMessages\(current, normalizeChatMessages\(response\.messages\)\)/, 'ChatPanel should keep stable message merging after edited-message retry');
assert.match(source, /useChatThesisWorkflow/, 'ChatPanel should delegate thesis workflow execution to a focused hook');
assert.doesNotMatch(source, /const runThesisWorkflow = async/, 'ChatPanel should not own thesis workflow execution inline');
assert.match(thesisWorkflowHookSource, /export function useChatThesisWorkflow/, 'useChatThesisWorkflow hook should be exported');
assert.match(thesisWorkflowHookSource, /THESIS_WORKFLOW_PROMPT/, 'thesis workflow hook should preserve the shared workflow prompt');
assert.match(thesisWorkflowHookSource, /api\.runSoilMoistureWorkflow\(userId, currentSessionId\)/, 'thesis workflow hook should preserve the session-scoped workflow API call');
assert.match(thesisWorkflowHookSource, /assistantReplyContent\(response\.reply\)/, 'thesis workflow hook should preserve assistant reply normalization');
assert.match(thesisWorkflowHookSource, /assistantErrorContent\(error\)/, 'thesis workflow hook should preserve assistant error normalization');
assert.match(thesisWorkflowHookSource, /setLastFailedPrompt\(prompt\)/, 'thesis workflow hook should preserve retry prompt on failure');
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
