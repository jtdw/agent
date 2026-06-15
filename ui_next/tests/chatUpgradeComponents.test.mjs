import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const artifactCard = await readFile('src/components/ArtifactDownloadCard.tsx', 'utf8');
const composer = await readFile('src/components/ChatComposer.tsx', 'utf8');
const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const chatPanel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const api = await readFile('src/lib/api.ts', 'utf8');
const productConsole = await readFile('src/components/ProductConsole.tsx', 'utf8');
const packageJson = await readFile('package.json', 'utf8');
const playwrightConfig = await readFile('playwright.config.ts', 'utf8');
const css = await readFile('src/index.css', 'utf8');

assert.match(api, /export type ChatArtifact/, 'api.ts must expose ChatArtifact');
assert.match(api, /meta\?: Record<string, unknown> & \{ artifacts\?: ChatArtifact\[\]/, 'ChatMessage meta must support artifacts');
assert.match(api, /signal\?: AbortSignal/, 'api.ask must accept AbortSignal for soft stop');
assert.match(api, /cancelChatTask/, 'api.ts must expose backend cooperative chat task cancellation');
assert.match(api, /downloadNative/, 'api.ts must expose native browser download for large artifacts');
assert.match(api, /deleteArtifact/, 'api.ts must expose artifact deletion by artifact_id');

assert.match(artifactCard, /export function ArtifactDownloadCard/, 'ArtifactDownloadCard must be exported');
assert.match(artifactCard, /downloadAuthenticated/, 'ArtifactDownloadCard must download through authenticated API helper');
assert.match(artifactCard, /downloadNative/, 'ArtifactDownloadCard must avoid blob buffering for large artifacts');
assert.match(artifactCard, /deleteArtifact/, 'ArtifactDownloadCard must support deleting result artifacts by artifact_id');
assert.match(artifactCard, /data-testid="artifact-delete"/, 'ArtifactDownloadCard must expose a stable delete button');
assert.match(artifactCard, /artifact\.filename/, 'ArtifactDownloadCard must show the safe server filename');
assert.match(artifactCard, /artifact\.mime_type/, 'ArtifactDownloadCard must expose MIME type');
assert.match(artifactCard, /formatFileSize/, 'ArtifactDownloadCard must show file size');
assert.match(artifactCard, /artifact\.created_at/, 'ArtifactDownloadCard must show creation time');
assert.match(artifactCard, /artifact\.source\?\.tool_name/, 'ArtifactDownloadCard must show source tool/workflow');
assert.match(artifactCard, /onDeleted\?\.\(artifact\.artifact_id\)/, 'ArtifactDownloadCard must notify parent after deletion');
assert.doesNotMatch(artifactCard, /artifact\.path[^?]/, 'ArtifactDownloadCard must not rely on server absolute paths');
assert.match(css, /\.artifact-download-card[\s\S]*min-width:\s*0/, 'Artifact cards must be allowed to shrink inside the floating chat panel');
assert.match(css, /\.artifact-download-card[\s\S]*max-width:\s*100%/, 'Artifact cards must not exceed the message container width');
assert.match(css, /\.artifact-file-name[\s\S]*overflow-wrap:\s*anywhere/, 'Artifact filenames must wrap instead of overflowing');
assert.match(css, /\.artifact-meta-line[\s\S]*min-width:\s*0/, 'Artifact metadata must shrink in narrow chat panels');
for (const label of ['未知大小', '未知时间', '来源', 'GIS 处理结果', '下载失败', '预览', '下载']) {
  assert.match(artifactCard, new RegExp(label), `ArtifactDownloadCard must contain ${label}`);
}

assert.match(composer, /export function ChatComposer/, 'ChatComposer must be exported');
assert.match(composer, /scrollHeight/, 'ChatComposer textarea must auto-grow from scrollHeight');
assert.match(composer, /maxComposerHeight/, 'ChatComposer must cap textarea height');
assert.match(composer, /onDrop/, 'ChatComposer must support drag-and-drop upload');
assert.match(composer, /onStop/, 'ChatComposer must expose stop action while sending');
assert.match(composer, /Shift\+Enter/, 'ChatComposer must document Shift+Enter behavior');
assert.doesNotMatch(composer, /data-testid="chat-language-selector"/, 'ChatComposer must not show language selection in the chat input bar');
assert.match(composer, /data-testid="chat-voice"/, 'ChatComposer must expose a voice input button');
assert.match(composer, /onVoiceToggle/, 'ChatComposer must connect voice input events to ChatPanel');

assert.match(renderer, /export function ChatMessageRenderer/, 'ChatMessageRenderer must be exported');
assert.match(packageJson, /react-markdown/, 'ChatMessageRenderer must use react-markdown for full Markdown coverage');
assert.match(packageJson, /remark-gfm/, 'ChatMessageRenderer must enable GFM tables and task lists');
assert.match(packageJson, /rehype-sanitize/, 'ChatMessageRenderer must sanitize rendered Markdown');
assert.match(renderer, /ReactMarkdown/, 'ChatMessageRenderer must render through ReactMarkdown');
assert.match(renderer, /remarkGfm/, 'ChatMessageRenderer must enable remark-gfm');
assert.match(renderer, /rehypeSanitize/, 'ChatMessageRenderer must enable rehype-sanitize');
assert.match(renderer, /CopyButton/, 'ChatMessageRenderer must expose stable copy controls');
assert.match(renderer, /navigator\.clipboard\.writeText/, 'Copy controls must use clipboard API');
assert.match(renderer, /copy-code/, 'Code blocks must expose copy-code controls');
assert.match(renderer, /artifact-download-list/, 'Renderer must render artifact cards');
assert.match(renderer, /selectionchange/, 'Renderer should support selected text copy affordance');
for (const label of ['复制', '复制代码', '复制选中文本', '已复制', '•']) {
  assert.match(renderer, new RegExp(label), `ChatMessageRenderer must contain ${label}`);
}

for (const source of [artifactCard, composer, renderer, api]) {
  assert.doesNotMatch(source, /鏈|澶嶅|宸插|涓嬭|鏉ユ|棰勮|娌℃|鐧诲|閺|娑|婢|閻|妫/, 'Chat files must not contain known mojibake fragments');
}

assert.match(chatPanel, /<ChatComposer/, 'ChatPanel must use ChatComposer');
assert.match(chatPanel, /<ChatMessageRenderer/, 'ChatPanel must use ChatMessageRenderer');
assert.match(chatPanel, /AbortController/, 'ChatPanel must use AbortController for soft stop');
assert.match(chatPanel, /safe-area-inset-bottom/, 'ChatPanel must reserve the mobile safe area for the composer');
assert.match(chatPanel, /data-testid="floating-chat-toolbar"/, 'Floating chat must have a compact toolbar');
assert.match(chatPanel, /data-testid="floating-chat-delete"/, 'Floating chat must expose delete/clear action');
assert.match(chatPanel, /toggleVoice/, 'ChatPanel must connect the visible composer voice button to speech recognition');
assert.match(productConsole, /activeTab === 'chat'/, 'ProductConsole must have a dedicated chat layout branch');
assert.match(chatPanel, /UploadResultCard/, 'ChatPanel must show compact upload result cards instead of raw upload JSON/text');
assert.match(playwrightConfig, /Desktop Firefox/, 'Playwright matrix must include Firefox');
assert.match(playwrightConfig, /Desktop Safari/, 'Playwright matrix must include WebKit/Safari');

console.log('chatUpgradeComponents.test.mjs passed');
