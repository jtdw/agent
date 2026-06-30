import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const appSource = await readFile('src/App.tsx', 'utf8');
const apiSource = await readFile('src/lib/api.ts', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');
const productConsoleSource = await readFile('src/components/ProductConsole.tsx', 'utf8');
const rendererSource = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');
const taskCardSource = await readFile('src/components/chat/task-card/TaskStatusCard.tsx', 'utf8');

assert.match(appSource, /currentSessionId/, 'App must own the current workspace chat session id');
assert.match(appSource, /onSessionChange=\{setCurrentSessionId\}/, 'App must receive session changes from ChatPanel');
assert.match(appSource, /sessionId=\{currentSessionId\}/, 'App must pass currentSessionId to action panels');

assert.match(apiSource, /exportWorkspace\(user_id\?: string,\s*session_id\?: string,\s*mode/, 'exportWorkspace must accept session_id before mode');
assert.match(apiSource, /request<\{\s*artifact_id: string;\s*download_url\?: string;\s*file_count: number/, 'exportWorkspace must expose artifact_id so callers do not depend on raw paths or raw download_url');
assert.doesNotMatch(apiSource, /exportWorkspace[\s\S]*?request<\{[^}]*zip_path/, 'exportWorkspace response type must not expose raw server zip_path');
assert.match(apiSource, /deleteWorkspaceArtifact\(input: \{ user_id\?: string; session_id\?: string; artifact_id: string \}/, 'deleteWorkspaceArtifact must require artifact_id and accept session_id');
assert.doesNotMatch(apiSource, /deleteWorkspaceArtifact\(input: \{[^}]*path\?: string/, 'deleteWorkspaceArtifact helper must not expose legacy path deletion');
assert.doesNotMatch(apiSource, /deleteWorkspaceArtifact[\s\S]*?request<\{[^>]*(path|deleted_files):/, 'deleteWorkspaceArtifact response type must not expose raw deleted paths');
assert.match(apiSource, /cancelDownloadJob\(job_id: string, user_id\?: string, reason\?: string, session_id\?: string\)/, 'cancelDownloadJob must keep session_id parameter');
assert.match(apiSource, /body: JSON\.stringify\(\{ user_id: user_id \|\| '', session_id: session_id \|\| '', job_id, reason/, 'cancelDownloadJob must send session_id');
assert.match(apiSource, /jobs\(user_id\?: string, session_id\?: string\)/, 'jobs must accept session_id');
const downloadJobType = apiSource.match(/export type DownloadJob = \{[\s\S]*?\n\};/)?.[0] || '';
assert.ok(downloadJobType, 'api.ts must define the UI DownloadJob projection type');
assert.doesNotMatch(downloadJobType, /\b(output_path|zip_path|download_url)\?:/, 'DownloadJob UI projection must not expose raw server path or raw download URL fields');
const resultPanelFileType = apiSource.match(/export type ResultPanelFile = \{[\s\S]*?\n\};/)?.[0] || '';
assert.ok(resultPanelFileType, 'api.ts must define the ResultPanelFile contract');
assert.doesNotMatch(resultPanelFileType, /\b(path|download_url)\?:/, 'ResultPanelFile must not expose raw path or raw download_url fields');
const workspaceArtifactType = apiSource.match(/export type WorkspaceArtifact = \{[\s\S]*?\n\};/)?.[0] || '';
assert.ok(workspaceArtifactType, 'api.ts must define the WorkspaceArtifact contract');
assert.doesNotMatch(workspaceArtifactType, /\bpath\?: string;/, 'WorkspaceArtifact must not expose legacy raw path metadata');
assert.doesNotMatch(workspaceArtifactType, /\bdownload_url\?: string;/, 'WorkspaceArtifact must not expose raw download_url metadata');
assert.doesNotMatch(apiSource, /async jobs[\s\S]*?request<\{[^>]*jobs\?: DownloadJob\[\]/, 'Default jobs() response type must not expose raw jobs without include_raw');
assert.doesNotMatch(apiSource, /async downloadJobLog[\s\S]*?request<\{[^>]*job\?: DownloadJob/, 'Default downloadJobLog() response type must not expose raw job without include_raw');
assert.doesNotMatch(apiSource, /async submitDownload[\s\S]*?request<\{[^>]*job\?:/, 'Default submitDownload() response type must not expose raw job without include_raw');
assert.doesNotMatch(apiSource, /async resumeDownloadJob[\s\S]*?request<\{[^>]*job: DownloadJob/, 'Default resumeDownloadJob() response type must not expose raw job');
assert.doesNotMatch(apiSource, /async (deleteDownloadJob|cancelDownloadJob|retryDownloadJob)[\s\S]*?request<[^>]*jobs\?: DownloadJob\[\]/, 'Default download lifecycle response types must not expose raw jobs arrays');
assert.match(apiSource, /preflightDownload\(input: \{\s*user_id: string;\s*session_id\?: string;/, 'preflightDownload must accept session_id');
assert.match(apiSource, /downloadJobLog\(user_id: string, job_id: string, session_id\?: string\)/, 'downloadJobLog must accept session_id');
assert.match(apiSource, /downloadJobLogFile\(user_id: string, job_id: string, session_id\?: string\)/, 'downloadJobLogFile must accept session_id');

assert.match(layerPanelSource, /sessionId\?: string/, 'LayerPanel props must include sessionId');
assert.match(layerPanelSource, /api\.exportWorkspace\(userId, sessionId, 'all'\)/, 'LayerPanel export must pass sessionId');
assert.match(layerPanelSource, /api\.downloadArtifactById\(r\.artifact_id,\s*'workspace-export\.zip',\s*userId,\s*sessionId\)/, 'LayerPanel export download must use artifact_id resolver');
assert.doesNotMatch(layerPanelSource, /downloadAuthenticated\(r\.download_url|downloadUrl\(r\.download_url/, 'LayerPanel export must not download from raw export download_url');
assert.match(layerPanelSource, /session_id: sessionId/, 'LayerPanel artifact delete must pass sessionId');
assert.doesNotMatch(layerPanelSource, /path: artifact\.path/, 'LayerPanel artifact delete must not send legacy path fallback');
assert.match(layerPanelSource, /api\.preflightDownload\(\{\s*user_id: user\.user_id,\s*session_id: sessionId,/s, 'LayerPanel preflight must pass sessionId');
assert.match(layerPanelSource, /api\.cancelDownloadJob\(job\.job_id, userId, .*sessionId\)/, 'LayerPanel cancel must pass sessionId');

assert.match(productConsoleSource, /sessionId\?: string/, 'ProductConsole props must include sessionId');
assert.match(productConsoleSource, /api\.exportWorkspace\(userId, sessionId, 'all'\)/, 'ProductConsole export must pass sessionId');
assert.match(productConsoleSource, /api\.downloadArtifactById\(result\.artifact_id,\s*'workspace-export\.zip',\s*userId,\s*sessionId\)/, 'ProductConsole export download must use artifact_id resolver');
assert.doesNotMatch(productConsoleSource, /downloadAuthenticated\(result\.download_url|downloadUrl\(result\.download_url/, 'ProductConsole export must not download from raw export download_url');
assert.doesNotMatch(productConsoleSource, /file\.label \|\| file\.path/, 'ProductConsole result panel files must not display raw path fallbacks');
assert.match(productConsoleSource, /session_id: sessionId/, 'ProductConsole artifact delete must pass sessionId');
assert.doesNotMatch(productConsoleSource, /path: artifact\.path/, 'ProductConsole artifact delete must not send legacy path fallback');
assert.match(productConsoleSource, /api\.preflightDownload\(\{\s*user_id: user\.user_id,\s*session_id: sessionId \|\| chatContext\?\.session_id,/s, 'ProductConsole preflight must pass active sessionId');
assert.match(productConsoleSource, /api\.cancelDownloadJob\(job\.job_id, userId, .*sessionId\)/, 'ProductConsole cancel must pass sessionId');

assert.doesNotMatch(rendererSource, /data-testid="technical-details"[\s\S]*Object\.keys\(debug\)\.length > 0/, 'technical details must not render for ordinary users by default');
assert.match(taskCardSource, /gis-agent-developer-mode|VITE_SHOW_TECHNICAL_DETAILS/, 'technical details must be gated by developer mode');

console.log('sessionScopedActions.test.mjs passed');
