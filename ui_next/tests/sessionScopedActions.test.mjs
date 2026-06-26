import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const appSource = await readFile('src/App.tsx', 'utf8');
const apiSource = await readFile('src/lib/api.ts', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');
const productConsoleSource = await readFile('src/components/ProductConsole.tsx', 'utf8');
const rendererSource = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');

assert.match(appSource, /currentSessionId/, 'App must own the current workspace chat session id');
assert.match(appSource, /onSessionChange=\{setCurrentSessionId\}/, 'App must receive session changes from ChatPanel');
assert.match(appSource, /sessionId=\{currentSessionId\}/, 'App must pass currentSessionId to action panels');

assert.match(apiSource, /exportWorkspace\(user_id\?: string,\s*session_id\?: string,\s*mode/, 'exportWorkspace must accept session_id before mode');
assert.match(apiSource, /deleteWorkspaceArtifact\(input: \{ user_id\?: string; session_id\?: string;/, 'deleteWorkspaceArtifact must accept session_id');
assert.match(apiSource, /cancelDownloadJob\(job_id: string, user_id\?: string, reason\?: string, session_id\?: string\)/, 'cancelDownloadJob must keep session_id parameter');
assert.match(apiSource, /body: JSON\.stringify\(\{ user_id: user_id \|\| '', session_id: session_id \|\| '', job_id, reason/, 'cancelDownloadJob must send session_id');
assert.match(apiSource, /jobs\(user_id\?: string, session_id\?: string\)/, 'jobs must accept session_id');
assert.match(apiSource, /preflightDownload\(input: \{\s*user_id: string;\s*session_id\?: string;/, 'preflightDownload must accept session_id');
assert.match(apiSource, /downloadJobLog\(user_id: string, job_id: string, session_id\?: string\)/, 'downloadJobLog must accept session_id');
assert.match(apiSource, /downloadJobLogFile\(user_id: string, job_id: string, session_id\?: string\)/, 'downloadJobLogFile must accept session_id');

assert.match(layerPanelSource, /sessionId\?: string/, 'LayerPanel props must include sessionId');
assert.match(layerPanelSource, /api\.exportWorkspace\(userId, sessionId, 'all'\)/, 'LayerPanel export must pass sessionId');
assert.match(layerPanelSource, /session_id: sessionId/, 'LayerPanel artifact delete must pass sessionId');
assert.match(layerPanelSource, /api\.preflightDownload\(\{\s*user_id: user\.user_id,\s*session_id: sessionId,/s, 'LayerPanel preflight must pass sessionId');
assert.match(layerPanelSource, /api\.cancelDownloadJob\(job\.job_id, userId, .*sessionId\)/, 'LayerPanel cancel must pass sessionId');

assert.match(productConsoleSource, /sessionId\?: string/, 'ProductConsole props must include sessionId');
assert.match(productConsoleSource, /api\.exportWorkspace\(userId, sessionId, 'all'\)/, 'ProductConsole export must pass sessionId');
assert.match(productConsoleSource, /session_id: sessionId/, 'ProductConsole artifact delete must pass sessionId');
assert.match(productConsoleSource, /api\.preflightDownload\(\{\s*user_id: user\.user_id,\s*session_id: sessionId \|\| chatContext\?\.session_id,/s, 'ProductConsole preflight must pass active sessionId');
assert.match(productConsoleSource, /api\.cancelDownloadJob\(job\.job_id, userId, .*sessionId\)/, 'ProductConsole cancel must pass sessionId');

assert.doesNotMatch(rendererSource, /data-testid="technical-details"[\s\S]*Object\.keys\(debug\)\.length > 0/, 'technical details must not render for ordinary users by default');
assert.match(rendererSource, /gis-agent-developer-mode|VITE_SHOW_TECHNICAL_DETAILS/, 'technical details must be gated by developer mode');

console.log('sessionScopedActions.test.mjs passed');
