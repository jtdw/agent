import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const panelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');
const composerFooterSource = await readFile('src/components/chat/ChatComposerFooter.tsx', 'utf8');
const hookSource = await readFile('src/components/chat/useChatStreamLifecycle.ts', 'utf8');
const promptStreamActionHook = await readFile('src/components/chat/useChatPromptStreamAction.ts', 'utf8');

assert.match(panelSource, /useChatStreamLifecycle/, 'ChatPanel should delegate stream lifecycle state to a focused hook');
assert.doesNotMatch(panelSource, /const \[thinking,\s*setThinking\] = useState\(false\)/, 'ChatPanel should not own the raw thinking state');
assert.doesNotMatch(panelSource, /const abortRef = useRef<AbortController \| null>\(null\)/, 'ChatPanel should not own the stream abort ref');
assert.doesNotMatch(panelSource, /const activeTaskIdRef = useRef<string>\(''\)/, 'ChatPanel should not own the active stream task ref');
assert.match(promptStreamActionHook, /await api\.streamChat\(/, 'Prompt stream hook should own the streaming API call');
assert.match(promptStreamActionHook, /streamLifecycle\.startTask\(taskId,\s*controller\)/, 'Prompt stream hook should register active stream tasks through the lifecycle hook');
assert.match(promptStreamActionHook, /streamLifecycle\.finishTask\(taskId,\s*controller\)/, 'Prompt stream hook should clear active stream tasks through the lifecycle hook');
assert.match(panelSource, /<ChatComposerFooter/, 'ChatPanel should delegate footer rendering to the composer footer component');
assert.match(panelSource, /stopCurrentRequest=\{streamLifecycle\.stopCurrentRequest\}/, 'ChatPanel should pass lifecycle stop into the composer footer');
assert.match(composerFooterSource, /onStop=\{stopCurrentRequest\}/, 'ChatComposer should stop through the lifecycle hook');

assert.match(hookSource, /export function useChatStreamLifecycle/, 'hook should export useChatStreamLifecycle');
assert.match(hookSource, /const \[thinking,\s*setThinking\] = useState\(false\)/, 'hook should own thinking state');
assert.match(hookSource, /abortRef/, 'hook should own the active AbortController ref');
assert.match(hookSource, /activeTaskIdRef/, 'hook should own the active task id ref');
assert.match(hookSource, /startTask/, 'hook should expose startTask');
assert.match(hookSource, /finishTask/, 'hook should expose finishTask');
assert.match(hookSource, /stopCurrentRequest/, 'hook should expose stopCurrentRequest');
assert.match(hookSource, /api\.cancelChatTask\(taskId,\s*userId,/, 'hook should preserve backend task cancellation');
assert.match(hookSource, /abortRef\.current\?\.abort\(\)/, 'hook should abort the active request locally');

console.log('chatStreamLifecycleHook.test.mjs passed');
