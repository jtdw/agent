import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const cssSource = await readFile('src/index.css', 'utf8');
const mapControlsSource = await readFile('src/components/MapControls.tsx', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');
const localLibrarySource = await readFile('src/components/LocalLibraryPanel.tsx', 'utf8');
const chatPanelSource = await readFile('src/components/ChatPanel.tsx', 'utf8');
const productConsoleSource = await readFile('src/components/ProductConsole.tsx', 'utf8');

for (const selector of ['glass-button', 'primary-button', 'floating-dock-button']) {
  const hoverBlock = cssSource.match(new RegExp(`\\.${selector}[^{}]*:hover[\\s\\S]*?\\}`))?.[0] || '';
  assert.doesNotMatch(hoverBlock, /transform\s*:/, `${selector} hover must not move or scale the element`);
  assert.doesNotMatch(hoverBlock, /filter\s*:/, `${selector} hover must not use filter because it can flicker over map/canvas surfaces`);
  assert.doesNotMatch(hoverBlock, /box-shadow\s*:/, `${selector} hover must not change shadow during hover`);
}

for (const selector of ['console-primary-button', 'console-secondary-button', 'console-icon-button', 'console-link-button']) {
  const block = cssSource.match(new RegExp(`\\.${selector}\\s*\\{[\\s\\S]*?\\}`))?.[0] || '';
  assert.doesNotMatch(block, /\btransition\b(?!-colors)/, `${selector} must avoid broad transition on high-frequency hover controls`);
  assert.match(block, /transition-colors/, `${selector} should only transition colors`);
}

assert.doesNotMatch(mapControlsSource, /whileHover=\{\{[^}]*scale/, 'MapControls must not scale controls on hover');
assert.doesNotMatch(mapControlsSource, /whileHover=\{\{[^}]*y:/, 'MapControls must not move controls on hover');

assert.doesNotMatch(layerPanelSource, /<motion\.aside\s+layout\b/, 'LayerPanel shell must not use layout animation');
assert.doesNotMatch(layerPanelSource, /whileHover=\{\{[^}]*x:/, 'LayerPanel layer rows must not move on hover');
assert.doesNotMatch(layerPanelSource, /layoutId="layer-active"/, 'LayerPanel active marker must not use shared layout animation');

assert.doesNotMatch(localLibrarySource, /<motion\.div\s+[\s\S]*?\blayout\b/, 'LocalLibrary cards must not use layout animation');
assert.doesNotMatch(localLibrarySource, /whileHover=\{\{[^}]*x:/, 'LocalLibrary cards must not move on hover');
assert.doesNotMatch(localLibrarySource, /hover:scale-/, 'LocalLibrary actions must not scale on hover');

assert.doesNotMatch(chatPanelSource, /key=\{`\$\{m\.role\}-\$\{idx\}`\}/, 'Chat messages must not use index-based keys');
assert.match(chatPanelSource, /messageKey\(/, 'ChatPanel must compute stable message keys');
assert.match(chatPanelSource, /pointer-events-none[\s\S]*group-hover:pointer-events-auto/, 'Chat hover actions should not create a new pointer target until hover is active');
const chatActionsBlock = cssSource.match(/\.chat-message-actions\s*\{[\s\S]*?\}/)?.[0] || '';
assert.doesNotMatch(chatActionsBlock, /position:\s*absolute/, 'Chat message copy actions must sit below the answer instead of covering text');
assert.match(chatActionsBlock, /margin-top:\s*\.65rem/, 'Chat message copy actions must reserve stable space below the answer');
assert.match(chatActionsBlock, /min-height:\s*0/, 'Chat message copy actions must not reserve vertical layout space');
assert.match(cssSource, /\.chat-table-wrap\s*\{[\s\S]*?max-width:\s*100%/, 'Chat tables must stay within the message bubble and scroll horizontally');

assert.doesNotMatch(productConsoleSource, /transition-all/, 'ProductConsole high-frequency panels must not use transition-all');
assert.doesNotMatch(productConsoleSource, /hover:scale-/, 'ProductConsole controls must not scale on hover');

console.log('hover stability tests passed');
