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

assert.match(consoleSource, /label:\s*'地图工作台'/, 'ProductConsole sidebar nav must expose a map workbench item');
assert.match(
  appSource,
  /onOpenMap=\{\(\) => \{\s*setConsoleOpen\(false\);\s*setChatOpen\(true\);\s*setToolsOpen\(true\);\s*\}\}/,
  'Opening the map workbench from the console must show the assistant and tools panels'
);
assert.match(
  appSource,
  /onClick=\{\(\) => \{\s*setConsoleOpen\(true\);\s*setChatOpen\(false\);\s*setToolsOpen\(false\);\s*\}\}/,
  'Returning to the console must hide both floating side panels'
);

assert.equal(data.normalizeTaskStatus('queued').label, '等待中');
assert.equal(data.normalizeTaskStatus('idle').label, '就绪');
assert.equal(data.normalizeTaskStatus('running').tone, 'running');
assert.equal(data.normalizeTaskStatus('waiting_login').label, '需要登录');
assert.equal(data.normalizeTaskStatus('waiting_manual').label, '需要处理');
assert.equal(data.normalizeTaskStatus('completed').label, '成功');
assert.equal(data.normalizeTaskStatus('failed').tone, 'failed');
assert.equal(data.normalizeTaskStatus('canceled').label, '已取消');
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
  { name: 'model_metrics.csv', download_url: '/metrics.csv' },
  { name: 'soil_map.png', download_url: '/soil.png' },
  { name: 'workspace.zip', download_url: '/workspace.zip' }
];

assert.deepEqual(
  data.groupArtifacts(artifacts).map((item) => [item.label, item.kind]),
  [
    ['model_metrics.csv', 'report'],
    ['soil_map.png', 'visual'],
    ['workspace.zip', 'archive']
  ]
);

console.log('product console data tests passed');
