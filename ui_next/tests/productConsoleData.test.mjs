import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function loadTs(path) {
  const source = await readFile(path, 'utf8');
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true
    }
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);
}

const data = await loadTs('src/components/productConsoleData.ts');
const consoleSource = await readFile('src/components/ProductConsole.tsx', 'utf8');
const appSource = await readFile('src/App.tsx', 'utf8');

assert.match(consoleSource, /openMap/, 'ProductConsole sidebar nav must expose a map workbench action');
assert.match(consoleSource, /地理空间数据云登录/, 'ProductConsole settings must expose the GSCloud login module');
assert.match(consoleSource, /CapabilityManagementPanel/, 'ProductConsole settings must expose knowledge and capability management');
assert.match(consoleSource, /checkGscloudLoginHealth/, 'ProductConsole settings must let users check GSCloud login health');
assert.match(consoleSource, /api\.loginHealth\(userId,\s*'gscloud',\s*'platform'\)/, 'GSCloud module must check platform account login state');
assert.match(consoleSource, /api\.loginHealth\(userId,\s*'gscloud',\s*'own'\)/, 'GSCloud module must check own account login state');
assert.match(consoleSource, /deleteWorkspaceArtifact/, 'ProductConsole must be able to delete workspace artifacts');
assert.match(consoleSource, /console-artifact-image-preview/, 'ProductConsole must show visual artifact thumbnails');
assert.match(consoleSource, /artifact\.kind === 'visual'/, 'ProductConsole must preview visual artifacts without changing downloads');
assert.match(consoleSource, /api\.artifactMetadata/, 'ProductConsole download actions must resolve artifact_id through the artifact resolver');
assert.doesNotMatch(consoleSource, /job\.download_url/, 'ProductConsole main download management path must not consume raw job.download_url');
assert.doesNotMatch(consoleSource, /if \(error\) return <StateMessage/, 'ProductConsole must not replace the whole page with a dashboard error banner');
assert.match(consoleSource, /\{error && <StateMessage tone="error">\{error\}<\/StateMessage>\}/, 'ProductConsole should show dashboard errors inline while preserving page content');
const openChatWorkspaceSource = consoleSource.match(/const openChatWorkspace = \(\) => \{[\s\S]*?\n  \};/)?.[0] || '';
assert.doesNotMatch(openChatWorkspaceSource, /onOpenChat\?\.\(\)/, 'ProductConsole chat tab must not also mount the floating ChatPanel');
assert.match(
  appSource,
  /onOpenMap=\{\(\) => \{\s*setConsoleOpen\(false\);\s*setChatOpen\(true\);\s*setToolsOpen\(true\);\s*\}\}/,
  'Opening the map workbench from the console must show the assistant and tools panels'
);

assert.equal(data.normalizeTaskStatus('running').tone, 'running');
assert.equal(data.normalizeTaskStatus('waiting_login').tone, 'blocked');
assert.equal(data.normalizeTaskStatus('completed').tone, 'succeeded');
assert.equal(data.normalizeTaskStatus('failed').tone, 'failed');
assert.deepEqual(data.DOWNLOAD_JOB_STATUS_KEYS, ['queued', 'running', 'waiting_login', 'waiting_manual', 'completed', 'failed', 'canceled']);

const jobs = [
  { job_id: 'job_1', status: 'running', progress: 45 },
  { job_id: 'job_2', status: 'queued', progress: 0 },
  { job_id: 'job_3', status: 'waiting_login', progress: 5 },
  { job_id: 'job_4', status: 'completed', progress: 100 },
  { job_id: 'job_5', status: 'failed', progress: 100 },
  { job_id: 'job_6', status: 'canceled', progress: 100 }
];

assert.deepEqual(data.summarizeJobs(jobs), {
  total: 6,
  active: 3,
  running: 1,
  waiting: 2,
  succeeded: 1,
  failed: 1,
  canceled: 1
});

const artifacts = [
  { artifact_id: 'artifact_metrics', name: 'model_metrics.csv', path: 'derived/model_metrics.csv' },
  { artifact_id: 'artifact_map', name: 'soil_map.png', path: 'plots/soil_map.png', download_url: '/legacy-map.png' },
  { artifact_id: 'artifact_zip', name: 'workspace.zip', path: 'exports/workspace.zip' },
  { name: 'legacy_orphan.csv', path: 'derived/legacy_orphan.csv', download_url: '/api/files/artifact?path=derived/legacy_orphan.csv' }
];

assert.deepEqual(
  data.groupArtifacts(artifacts).map((item) => [item.artifactId, item.label, item.path, item.kind, item.url]),
  [
    ['artifact_metrics', 'model_metrics.csv', 'derived/model_metrics.csv', 'report', ''],
    ['artifact_map', 'soil_map.png', 'plots/soil_map.png', 'visual', ''],
    ['artifact_zip', 'workspace.zip', 'exports/workspace.zip', 'archive', '']
  ]
);

console.log('product console data tests passed');
