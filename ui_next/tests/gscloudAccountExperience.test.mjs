import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const api = await readFile('src/lib/api.ts', 'utf8');
const settings = await readFile('src/components/SettingsPanel.tsx', 'utf8');
const productConsole = await readFile('src/components/ProductConsole.tsx', 'utf8');
const account = await readFile('src/components/GSCloudAccountPanel.tsx', 'utf8');
const chat = await readFile('src/components/ChatPanel.tsx', 'utf8');
const renderer = await readFile('src/components/ChatMessageRenderer.tsx', 'utf8');

for (const method of ['gscloudStatus', 'startGSCloudLogin', 'completeGSCloudLogin', 'logoutGSCloud', 'resumeDownloadJob']) {
  assert.match(api, new RegExp(method), `api.ts must expose ${method}`);
}
assert.match(settings, /GSCloudAccountPanel/, 'settings must include the data-source account panel');
assert.match(productConsole, /GSCloudAccountPanel/, 'product console settings must include the data-source account panel');
assert.match(productConsole, /enabled=\{Boolean\(user\)\}/, 'product console account panel must follow the signed-in user');
assert.doesNotMatch(account, /setInterval/, 'login completion polling must not overlap requests');
assert.match(settings, /我的数据源账号/, 'settings must label the account section');
assert.match(account, /地理空间数据云账号/, 'account panel must identify GSCloud');
assert.match(account, /账号密码不会保存在聊天记录中/, 'account panel must explain password safety');
for (const label of ['登录', '重新登录', '退出登录']) {
  assert.match(account, new RegExp(label), `account panel must include ${label}`);
}
assert.match(chat, /login_required/, 'chat must react to login_required messages');
assert.match(chat, /GSCloudAccountPanel/, 'chat must open the shared login guide');
assert.match(chat, /100dvh/, 'login guide must fit mobile viewport');
assert.match(chat, /watchDownloadJob/, 'chat must monitor a resumed download job');
assert.match(chat, /meta: \{ artifacts/, 'chat must append completed job artifacts to an assistant message');
assert.match(renderer, /去登录/, 'chat action card must expose login action');
assert.match(renderer, /继续下载/, 'chat action card must expose resume action');
assert.match(renderer, /取消任务/, 'chat action card must expose cancel action');

console.log('gscloudAccountExperience.test.mjs passed');
