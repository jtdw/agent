import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const files = await Promise.all([
  readFile('src/components/AuthPanel.tsx', 'utf8'),
  readFile('src/components/SettingsPanel.tsx', 'utf8'),
  readFile('src/components/AnalysisPanel.tsx', 'utf8'),
  readFile('src/components/CapabilityManagementPanel.tsx', 'utf8'),
  readFile('src/components/LayerPanel.tsx', 'utf8'),
  readFile('src/components/LocalLibraryPanel.tsx', 'utf8'),
  readFile('src/components/ProductConsole.tsx', 'utf8'),
  readFile('src/components/ChatMessageRenderer.tsx', 'utf8'),
  readFile('src/components/ArtifactDownloadCard.tsx', 'utf8'),
  readFile('src/components/UploadResultCard.tsx', 'utf8'),
  readFile('src/components/MapStage.tsx', 'utf8'),
  readFile('task-card-harness.html', 'utf8'),
]);

const combined = files.join('\n');

assert.doesNotMatch(combined, /GIS Agent Task Card Harness/, 'Visual harness title should be Chinese');
assert.doesNotMatch(combined, /Test retrieval query/, 'Capability management placeholders should be Chinese');
assert.doesNotMatch(combined, /product_id，例如/, 'Capability management product id helper should be Chinese');
assert.doesNotMatch(combined, /selected model result/, 'Analysis panel user focus hint should be Chinese');
assert.doesNotMatch(combined, /\bMetric\b/, 'Settings panel distance unit should be Chinese');
assert.doesNotMatch(combined, /\bBASIC\b|\bPRO\b|\bTEAM\b/, 'Plan labels and auth copy should be Chinese');
assert.doesNotMatch(combined, /status \|\| 'unknown'|verification_method \|\| 'unknown'|item\.status \|\| 'unknown'/, 'Visible unknown fallbacks should be Chinese');
assert.doesNotMatch(combined, /artifact'\)|\|\| 'artifact'|tool_name \|\| 'tool'/, 'Visible artifact and tool fallbacks should be Chinese');
assert.doesNotMatch(combined, /\bPlanner\b|\bValidator\b|\bProduct Catalog\b|生成 draft 档案|上传为 draft/, 'Capability management descriptions should be Chinese');
assert.doesNotMatch(combined, />task_id:|>status:|>stage:|>progress:|>source:|>message:/, 'Visible task log field labels should be Chinese');
assert.doesNotMatch(combined, /\$\{item\.layer\.feature_count\} features|kind \|\| 'result'|\|\| 'file'|\|\| 'station'|\|\| 'info'/, 'Visible metadata fallbacks should be Chinese');

assert.match(combined, /基础版|专业版|团队版/, 'Plan labels should expose Chinese names');
assert.match(combined, /测试检索问题|检索测试/, 'Capability management should expose Chinese search guidance');
assert.match(combined, /工作区成果汇总|成果文件|结果文件/, 'Visible artifact fallbacks should be Chinese');
assert.match(combined, /任务编号：|任务状态：|执行阶段：|完成进度：|数据来源：/, 'Task log fields should expose Chinese labels');

console.log('frontendChineseCopy.test.mjs passed');
