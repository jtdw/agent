import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const panel = await readFile('src/components/ChatPanel.tsx', 'utf8');
const api = await readFile('src/lib/api.ts', 'utf8');

assert.match(renderer, /confirmation_required/, 'ChatMessageRenderer must render confirmation-required actions');
assert.match(renderer, /onConfirmAction/, 'ChatMessageRenderer must expose a confirmation callback');
assert.match(renderer, /confirmed_action_id/, 'Confirmation UI must pass the backend confirmation token');
assert.match(renderer, /data-testid="download-confirmation-required"/, 'Confirmation action should have a stable test id');
assert.match(panel, /confirmAction/, 'ChatPanel must implement a confirmAction handler');
assert.match(panel, /confirmed_action_id=\$\{/, 'ChatPanel must resend the original request with the confirmation token');
assert.match(panel, /onConfirmAction=\{confirmAction\}/, 'ChatPanel must wire confirmation callback into the message renderer');
assert.match(api, /confirmation_required/, 'ChatActionRequired type must explicitly include confirmation_required');
assert.match(api, /confirmed_action_id\?: string/, 'ChatActionRequired type must expose confirmed_action_id');
assert.match(api, /confirmation_prompt\?: string/, 'ChatActionRequired type must expose confirmation_prompt');

console.log('chat confirmation action tests passed');
