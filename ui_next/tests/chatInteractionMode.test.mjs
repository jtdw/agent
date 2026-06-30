import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const panel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const composerFooter = await readFile('src/components/chat/ChatComposerFooter.tsx', 'utf8');
const conversationHeader = await readFile('src/components/chat/ChatConversationHeader.tsx', 'utf8');
const interactionModeActionHook = await readFile('src/components/chat/useChatInteractionModeAction.ts', 'utf8');
const api = await readFile('src/lib/api.ts', 'utf8');

assert.match(api, /interaction_mode\?: 'chat_only' \| 'tool_enabled'/, 'ChatSession must expose safe interaction_mode');
assert.match(api, /setChatInteractionMode/, 'API client must expose setChatInteractionMode');
assert.match(api, /\/api\/chat\/sessions\/mode/, 'Mode switch must use the backend session mode endpoint');

assert.match(panel, /<ChatComposerFooter/, 'ChatPanel must render the composer footer component');
assert.doesNotMatch(composerFooter, /data-testid="interaction-mode-chat"|data-testid="interaction-mode-tool"/, 'Composer footer should not duplicate the header mode switch');
assert.match(conversationHeader, /data-testid="interaction-mode-chat"/, 'Conversation header must render the chat mode segment');
assert.match(conversationHeader, /data-testid="interaction-mode-tool"/, 'Conversation header must render the tool mode segment');
assert.match(interactionModeActionHook, /api\.setChatInteractionMode/, 'Interaction mode hook must call the mode switch API');
assert.match(panel, /聊天模式：只回答问题，不会操作数据或创建任务。/, 'Chat mode must describe zero data operations');
assert.match(panel, /工具模式：可以在确认和校验后执行下载、GIS 处理和建模。/, 'Tool mode must describe validated execution');
assert.equal(panel.includes('currentInteractionMode'), true);

console.log('chat interaction mode tests passed');
