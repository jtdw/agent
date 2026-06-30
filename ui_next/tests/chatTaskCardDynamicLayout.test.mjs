import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const taskCard = await readFile('src/components/chat/task-card/TaskStatusCard.tsx', 'utf8');
const composerFooter = await readFile('src/components/chat/ChatComposerFooter.tsx', 'utf8');
const conversationHeader = await readFile('src/components/chat/ChatConversationHeader.tsx', 'utf8');
const chatPanel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const productConsole = await readFile('src/components/ProductConsole.tsx', 'utf8');
const css = await readFile('src/index.css', 'utf8');

assert.match(taskCard, /function inferTaskKind/, 'Task card should infer task kind before building public steps');
assert.match(taskCard, /const TASK_STEP_TEMPLATES/, 'Task card should keep task-specific process templates');
assert.match(taskCard, /download-discover/, 'Download tasks should expose discovery/download oriented steps');
assert.match(taskCard, /map-render/, 'Map/cartography tasks should expose render/export oriented steps');
assert.match(taskCard, /vector-validate/, 'Vector/table/raster checks should expose data validation steps');
assert.match(taskCard, /agent-process-step-card/, 'Task timeline should use a dedicated animated step card class');
assert.match(taskCard, /task-card-motion-rail/, 'Task card should include a subtle motion rail for active work');
assert.match(taskCard, /data-task-kind=\{taskKind\}/, 'Task card should expose task kind for styling and visual checks');

assert.doesNotMatch(composerFooter, /常用指令|chat-quick-prompt-row|quickPrompts\.slice/, 'Composer footer should remove quick prompt chips from the chat bar');
assert.doesNotMatch(composerFooter, /chat-composer-mode-panel|interaction-mode-chat|interaction-mode-tool/, 'Composer footer should not render the chat/tool mode switch after it moves to the header');
assert.match(conversationHeader, /chat-header-mode-panel/, 'Conversation header should keep the chat/tool mode switch');

assert.match(chatPanel, /data-testid="chat-page-workspace"[\s\S]*lg:grid-cols-\[190px_minmax\(0,1fr\)_340px\]/, 'Chat page should use a narrower conversation area with a wider workbench rail');
assert.match(chatPanel, /rounded-none border-0 bg-white\/90/, 'Chat page workspace should fill the available boundaries instead of floating as a rounded card');
assert.match(productConsole, /activeTab === 'chat' \? 'overflow-hidden p-0'/, 'Product console should remove outer content padding on the chat tab');

assert.match(css, /\.agent-task-card::before/, 'Task card should have a CSS-only motion sheen');
assert.match(css, /@keyframes taskCardFlow/, 'Task card should define a reduced-risk motion keyframe');
assert.match(css, /\.agent-process-step-card\.is-active/, 'Active process steps should have a distinct dynamic state');
assert.match(css, /\.chat-session-rail\s*\{[\s\S]*padding:\s*0\.65rem/, 'Session sidebar should be visually tighter');
assert.match(css, /\.chat-header-mode-panel\s*\{[\s\S]*display:\s*inline-flex/, 'Header mode switch should align in the top toolbar');
assert.match(css, /\.chat-composer-footer\s*\{[\s\S]*background:\s*transparent/, 'Composer footer should not keep a visible backing plate');

console.log('chatTaskCardDynamicLayout.test.mjs passed');
