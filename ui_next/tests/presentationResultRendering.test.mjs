import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const api = await readFile('src/lib/api.ts', 'utf8');
const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const chatPanel = await readFile('src/components/ChatPanel.tsx', 'utf8');

assert.match(api, /export type PresentationResult/, 'api.ts must expose PresentationResult');
assert.match(api, /presentation_result\?: PresentationResult/, 'ChatMessage meta must include presentation_result');
assert.match(api, /execution_summary\?: ExecutionSummary/, 'ChatMessage meta must include execution_summary');

assert.match(renderer, /presentationResultFromMessage/, 'ChatMessageRenderer must read presentation_result');
assert.match(renderer, /presentation-result-card/, 'ChatMessageRenderer must render a presentation result card');
assert.match(renderer, /presentationResult \|\| userResult/, 'presentation_result must be preferred before user_facing_result fallback');
assert.doesNotMatch(renderer, /execution_trace/, 'ChatMessageRenderer must not render raw execution_trace');

assert.match(chatPanel, /function responseAssistantMessage/, 'ChatPanel must normalize backend chat responses through one assistant message adapter');
assert.match(chatPanel, /presentation_result: response\.presentation_result/, 'ChatPanel adapter must preserve presentation_result from chat responses');
assert.match(chatPanel, /execution_summary: response\.execution_summary/, 'ChatPanel adapter must preserve execution_summary from chat responses');

console.log('presentationResultRendering.test.mjs passed');
