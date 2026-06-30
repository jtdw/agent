import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const composer = await readFile('src/components/ChatComposer.tsx', 'utf8');
const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const chatPanel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const sessionSidebar = await readFile('src/components/chat/ChatSessionSidebar.tsx', 'utf8');
const messageList = await readFile('src/components/chat/ChatMessageList.tsx', 'utf8');
const chatUploadsHook = await readFile('src/components/chat/useChatUploads.ts', 'utf8');
const promptStreamActionHook = await readFile('src/components/chat/useChatPromptStreamAction.ts', 'utf8');
const confirmationActionHook = await readFile('src/components/chat/useChatConfirmationAction.ts', 'utf8');
const api = await readFile('src/lib/api.ts', 'utf8');
const productConsole = await readFile('src/components/ProductConsole.tsx', 'utf8');
const analysisPanelData = await readFile('src/components/analysisPanelData.ts', 'utf8');
const layerPanel = await readFile('src/components/LayerPanel.tsx', 'utf8');

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
assert.match(renderer, /user-facing-result-card/, 'ChatMessageRenderer must render user-facing result cards');
assert.match(renderer, /查看技术详情/, 'ChatMessageRenderer must hide raw workflow details behind a technical details control');
assert.match(renderer, /展开全部文件/, 'ChatMessageRenderer must let users expand secondary artifacts');
assert.match(renderer, /gscloud-login-required/, 'ChatMessageRenderer must render GSCloud login-required action');
const artifactCard = await readFile('src/components/ArtifactDownloadCard.tsx', 'utf8');
assert.match(artifactCard, /isImageArtifact/, 'ArtifactDownloadCard must detect image artifacts');
assert.match(artifactCard, /data-testid="artifact-image-preview"/, 'ArtifactDownloadCard must render image previews');
assert.match(artifactCard, /data-testid="artifact-table-preview"/, 'ArtifactDownloadCard must render table previews when provided');
assert.match(artifactCard, /data-testid="artifact-markdown-preview"/, 'ArtifactDownloadCard must render markdown previews when provided');
assert.match(artifactCard, /artifact-preview-image/, 'ArtifactDownloadCard image preview must use a stable CSS class');
assert.match(artifactCard, /data-testid="artifact-download"/, 'ArtifactDownloadCard must keep the download button');
assert.match(artifactCard, /status.*missing|missing.*status|文件失效|鏂囦欢澶辨晥/, 'ArtifactDownloadCard must expose a missing-file state');

assert.match(chatPanel, /export function ChatWorkspace/, 'ChatPanel must expose page and floating chat workspace');
assert.match(chatPanel, /<ChatComposer/, 'ChatPanel must use ChatComposer');
assert.match(chatPanel, /<ChatMessageList/, 'ChatPanel must use ChatMessageList');
assert.match(messageList, /<ChatMessageRenderer/, 'ChatMessageList must use ChatMessageRenderer');
assert.match(chatPanel, /chatModels/, 'ChatPanel must load and render model selection');
assert.match(chatPanel, /workspaceMentions/, 'ChatPanel must load workspace @ mentions');
assert.match(chatPanel, /useChatUploads/, 'ChatPanel should delegate upload control to a focused hook');
assert.doesNotMatch(chatPanel, /api\.uploadFiles|setUploading/, 'ChatPanel should not own upload API calls or upload state after hook extraction');
assert.match(chatUploadsHook, /export function useChatUploads/, 'useChatUploads hook should be exported');
assert.match(chatUploadsHook, /api\.uploadFiles\(files, userId, sessionId\)/, 'useChatUploads should preserve session-scoped upload API calls');
assert.match(chatUploadsHook, /normalizeWorkspaceMentions/, 'useChatUploads should refresh workspace mentions from upload dashboard datasets');
assert.match(chatUploadsHook, /sanitizeUploadSummaries/, 'useChatUploads should sanitize legacy upload summaries before storing message meta');
assert.doesNotMatch(chatUploadsHook, /upload_summaries: r\.upload_summaries \|\| \[\]/, 'useChatUploads must not persist raw upload summaries from legacy responses');
assert.doesNotMatch(chatUploadsHook, /safeBasename\(raw\.path\)/, 'useChatUploads must not derive visible upload names from legacy raw paths');
assert.doesNotMatch(api.match(/export type UploadSummary[\s\S]*?};/)?.[0] || '', /\n\s*path\?: string;/, 'UploadSummary must not expose raw upload paths to chat message meta');
const chatArtifactType = api.match(/export type ChatArtifact = \{[\s\S]*?\n\};/)?.[0] || '';
assert.ok(chatArtifactType, 'api.ts must define the ChatArtifact contract');
assert.doesNotMatch(chatArtifactType, /\bpath\?: string;/, 'ChatArtifact must not expose raw artifact paths to chat message meta');
assert.doesNotMatch(chatArtifactType, /\bdownload_url\?: string;/, 'ChatArtifact must not expose raw download URLs to chat message meta');
assert.match(chatPanel, /<ChatSessionSidebar/, 'ChatPanel must render session/data partition area through ChatSessionSidebar');
assert.match(sessionSidebar, /data-testid="chat-session-list"/, 'ChatSessionSidebar must preserve the session/data partition area');
assert.ok(/AbortController/.test(promptStreamActionHook) && /AbortController/.test(confirmationActionHook), 'Prompt and confirmation hooks must support cooperative stop');

assert.match(productConsole, /activeTab === 'chat'/, 'ProductConsole must have a dedicated chat layout branch');
assert.match(productConsole, /<ChatWorkspace/, 'ProductConsole chat tab must embed ChatWorkspace');
assert.match(analysisPanelData, /filename \|\| item\.label \|\| item\.name \|\| '成果文件'|filename \|\| item\.label \|\| item\.name \|\| '鎴愭灉鏂囦欢'/, 'AnalysisPanel downloads should prefer safe artifact labels over raw path');
assert.doesNotMatch(analysisPanelData, /item\.label \|\| item\.path/, 'AnalysisPanel downloads must not display raw artifact paths before safe labels');
assert.doesNotMatch(layerPanel, /item\.path\.split/, 'LayerPanel recent artifacts must not derive visible labels from raw paths');

console.log('chatUpgradeComponents.test.mjs passed');
