import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const composer = await readFile('src/components/ChatComposer.tsx', 'utf8');
const messageList = await readFile('src/components/chat/ChatMessageList.tsx', 'utf8');
const css = await readFile('src/index.css', 'utf8');

assert.match(composer, /import \{[^}]*AudioLines[^}]*Plus[^}]*\} from 'lucide-react'/s, 'Composer should use Codex-like plus and voice waveform icons');
assert.match(composer, /<Plus size=\{20\}/, 'Upload affordance should render as a plus icon like the reference bar');
assert.match(composer, /className=\{cn\('chat-composer-voice-pill'/, 'Voice input should render as a rounded text pill');
assert.match(composer, /<AudioLines size=\{15\}/, 'Voice pill should include a compact waveform icon');

assert.match(css, /\.chat-composer-shell\s*\{[\s\S]*border-radius:\s*999px/, 'Composer shell should be a single rounded Codex-style pill');
assert.match(css, /\.chat-composer-input-frame\s*\{[\s\S]*align-items:\s*center/, 'Composer frame should vertically center the single-line pill controls');
assert.match(css, /\.chat-composer-voice-pill\s*\{[\s\S]*border-radius:\s*999px[\s\S]*font-weight:\s*800/, 'Voice control should be a compact pill with stable label weight');
assert.match(css, /\.chat-composer-mode-copy\s*\{[^}]*display:\s*none/, 'Composer mode helper copy should not collapse into vertical text beside the input');
assert.match(css, /\.chat-user-bubble\s*\{[\s\S]*align-items:\s*center[\s\S]*justify-content:\s*center/, 'User bubbles should center their text inside the Codex-like capsule');
assert.match(css, /\.chat-session-new-action\s*\{[\s\S]*justify-content:\s*flex-start/, 'New conversation action should use a clearer sidebar layout');

assert.doesNotMatch(messageList, /bg-gradient-to-br from-blue-600 to-cyan-600/, 'User bubbles should not use the old blue/cyan gradient');
assert.match(messageList, /isUser && !isEditing && 'chat-user-bubble max-w-\[min\(72%,36rem\)\][^']*bg-white/, 'Regular user bubbles should use a neutral Codex-like surface');
assert.match(messageList, /isUser && isEditing && 'w-full max-w-\[min\(92%,54rem\)\]/, 'Edited user messages should get a wider editing container');
assert.match(messageList, /className="chat-message-edit-textarea"/, 'Edited message textarea should use a dedicated spacious class');
assert.match(css, /\.chat-message-edit-textarea\s*\{[\s\S]*min-height:\s*9rem[\s\S]*width:\s*100%/, 'Edited message textarea should be taller and full-width');

console.log('chatCodexComposerVisual.test.mjs passed');
