import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const apiSource = await readFile('src/lib/api.ts', 'utf8');
const chatPanelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');
const composerSource = await readFile('src/components/ChatComposer.tsx', 'utf8');
const productConsoleSource = await readFile('src/components/ProductConsole.tsx', 'utf8');

assert.match(apiSource, /export type WorkspaceMention/, 'API types must expose compact workspace mention items');
assert.match(apiSource, /workspaceMentions\(user_id\?: string\)/, 'API helper must load compact workspace mentions');
assert.match(apiSource, /\/api\/workspace\/mentions/, 'workspaceMentions must call the compact mentions endpoint');

assert.match(chatPanelSource, /mentionDatasets\?:[^;]*WorkspaceMention/, 'ChatWorkspace must accept mention datasets from parent surfaces');
assert.match(chatPanelSource, /api\.workspaceMentions\(userId\)/, 'ChatWorkspace must refresh mention datasets through the compact API');
assert.match(chatPanelSource, /setWorkspaceMentions\(normalizeWorkspaceMentions/, 'ChatWorkspace must normalize mentions before rendering the picker');
assert.match(chatPanelSource, /mentionItems=\{workspaceMentions\}/, 'ChatWorkspace must pass mention items into ChatComposer');
assert.doesNotMatch(chatPanelSource, /api\.dashboard/, 'ChatWorkspace must not fetch the full dashboard for mention suggestions');

assert.match(composerSource, /mentionItems\?: WorkspaceMention\[\]/, 'ChatComposer must accept mention suggestions');
assert.match(composerSource, /data-testid="chat-mention-trigger"/, 'ChatComposer must expose a visible mention trigger');
assert.match(composerSource, /data-testid="chat-mention-menu"/, 'ChatComposer must render a mention menu');
assert.match(composerSource, /@\{/, 'Mention insertion must use a stable @{dataset_name} token');
assert.match(composerSource, /ArrowDown/, 'Mention menu must support keyboard navigation');
assert.match(composerSource, /Enter/, 'Mention menu must support keyboard selection');

assert.match(productConsoleSource, /mentionDatasets=\{dashboard\?\.datasets \|\| \[\]\}/, 'Console chat page must pass current dashboard datasets to ChatWorkspace');

console.log('chatMentionPicker.test.mjs passed');
