import { expect, test, type Page, type APIResponse } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

type ChatAskBody = {
  prompt?: string;
  session_id?: string;
  frontend_context?: Record<string, unknown>;
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const fixtureDir = path.resolve(__dirname, '..', '..', 'tests', 'fixtures');

function fixturePath(name: string) {
  return path.join(fixtureDir, name);
}

function uniqueEmail(prefix: string) {
  return `${prefix}.${Date.now()}.${Math.random().toString(16).slice(2)}@example.com`;
}

async function register(page: Page, prefix: string) {
  await page.goto('/');
  await page.getByTestId('auth-open').click();
  await page.getByTestId('auth-mode-toggle').click();
  await page.getByTestId('auth-email').fill(uniqueEmail(prefix));
  await page.getByTestId('auth-password').fill('TestPassword123!');
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/auth/register') && response.status() === 200),
    page.getByTestId('auth-submit').click(),
  ]);
}

async function openWorkspace(page: Page) {
  await page.getByTestId('open-map-workspace').first().click();
  await expect(page.getByTestId('chat-input')).toBeVisible();
}

async function enableToolMode(page: Page) {
  const toolButton = page.getByTestId('interaction-mode-tool');
  await expect(toolButton).toBeVisible();
  const [response] = await Promise.all([
    page.waitForResponse((item) => item.url().includes('/api/chat/sessions/mode') && item.request().method() === 'POST'),
    toolButton.click(),
  ]);
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.interaction_mode).toBe('tool_enabled');
  expect((body.sessions || []).some((session: Record<string, unknown>) => session.interaction_mode === 'tool_enabled')).toBeTruthy();
  await expect(toolButton).toHaveAttribute('aria-pressed', 'true');
}

async function uploadFixture(page: Page, name: string) {
  const [response] = await Promise.all([
    page.waitForResponse((item) => item.url().includes('/api/files/upload') && item.status() === 200),
    page.getByTestId('chat-file-input').setInputFiles(fixturePath(name)),
  ]);
  const body = await response.json();
  expect(body.ok).toBeTruthy();
  expect(body.count).toBeGreaterThan(0);
}

async function uploadFixtures(page: Page, names: string[]) {
  const [response] = await Promise.all([
    page.waitForResponse((item) => item.url().includes('/api/files/upload') && item.status() === 200),
    page.getByTestId('chat-file-input').setInputFiles(names.map((name) => fixturePath(name))),
  ]);
  const body = await response.json();
  expect(body.ok).toBeTruthy();
  expect(body.count).toBeGreaterThan(0);
}

async function sendChat(page: Page, text: string): Promise<{ requestBody: ChatAskBody; responseBody: Record<string, unknown>; response: APIResponse }> {
  const responsePromise = page.waitForResponse((response) => response.url().includes('/api/chat/stream') && response.request().method() === 'POST');
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const requestBody = response.request().postDataJSON() as ChatAskBody;
  const raw = (await response.body()).toString('utf8');
  const events = raw.split(/\r?\n\r?\n/).flatMap((frame) => {
    const data = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))?.slice(5).trim();
    if (!data) return [];
    try { return [JSON.parse(data) as Record<string, unknown>]; } catch { return []; }
  });
  const complete = [...events].reverse().find((event) => event.kind === 'model_complete') || {};
  const taskUpdate = (complete.task_update || {}) as Record<string, unknown>;
  const responseBody: Record<string, unknown> = {
    ...taskUpdate,
    reply: complete.delta || complete.message || '',
    presentation_result: complete.presentation_result || taskUpdate.presentation_result || {},
    current_session_id: requestBody.session_id || '',
  };
  expect(String(responseBody.reply || '').length).toBeGreaterThan(0);
  return { requestBody, responseBody, response };
}

function presentation(body: Record<string, unknown>) {
  return (body.presentation_result || {}) as Record<string, unknown>;
}

function artifactRefs(body: Record<string, unknown>) {
  return ((presentation(body).artifact_refs || []) as Array<Record<string, unknown>>);
}

function mapLayerRefs(body: Record<string, unknown>) {
  return ((presentation(body).map_layer_refs || []) as Array<Record<string, unknown>>);
}

function tableRefs(body: Record<string, unknown>) {
  return ((presentation(body).table_refs || []) as Array<Record<string, unknown>>);
}

function executedSteps(body: Record<string, unknown>) {
  return ((presentation(body).executed_steps || []) as Array<Record<string, unknown>>);
}

async function expectArtifactDownload(page: Page, body: Record<string, unknown>, artifact: Record<string, unknown>) {
  const artifactId = String(artifact.artifact_id || '');
  const sessionId = String(body.current_session_id || '');
  expect(artifactId).toBeTruthy();
  const metadata = await page.request.get(`/api/artifacts/${encodeURIComponent(artifactId)}?session_id=${encodeURIComponent(sessionId)}`);
  expect(metadata.status()).toBe(200);
  const meta = await metadata.json();
  expect(String(meta.download_url || '')).toBeTruthy();
  const download = await page.request.get(String(meta.download_url));
  expect(download.status()).toBe(200);
  expect((await download.body()).byteLength).toBeGreaterThan(0);
}

async function deleteSessionAndExpectArtifactBlocked(page: Page, body: Record<string, unknown>, artifact: Record<string, unknown>, layerRefs: Array<Record<string, unknown>> = []) {
  const artifactId = String(artifact.artifact_id || '');
  const sessionId = String(body.current_session_id || '');
  const deletion = await page.request.post('/api/chat/sessions/delete', { data: { session_id: sessionId } });
  expect(deletion.status()).toBe(200);
  const metadata = await page.request.get(`/api/artifacts/${encodeURIComponent(artifactId)}?session_id=${encodeURIComponent(sessionId)}`);
  expect(metadata.status()).not.toBe(200);
  const layersResponse = await page.request.get(`/api/map/layers?session_id=${encodeURIComponent(sessionId)}`);
  if (layersResponse.status() === 200) {
    const layersBody = await layersResponse.json();
    const activeLayerIds = ((layersBody.layers || []) as Array<Record<string, unknown>>).map((layer) => String(layer.id || layer.layer_id || ''));
    for (const layer of layerRefs) {
      expect(activeLayerIds).not.toContain(String(layer.layer_id || ''));
    }
  }
}

function captureConsoleProblems(page: Page) {
  const problems: string[] = [];
  page.on('console', (message) => {
    const text = message.text();
    if (/unique "key"|unique key|unhandled promise|unhandledrejection|token|session_id|user_id|traceback|raw dict/i.test(text)) {
      problems.push(text);
    }
  });
  page.on('pageerror', (error) => problems.push(error.message));
  return problems;
}

async function selectFirstArtifact(page: Page) {
  page.context().on('page', (popup) => void popup.close().catch(() => {}));
  await page.getByTestId('analysis-panel-open').click();
  const item = page.getByTestId('analysis-artifact-item').first();
  await expect(item).toBeVisible();
  await item.click();
  await page.getByTestId('analysis-panel-close').click();
}

test('real backend browser flow uploads GeoJSON, maps, and explains selected result', async ({ page }) => {
  await register(page, 'geojson');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixture(page, 'e2e_counties.geojson');

  const check = await sendChat(page, 'check this dataset');
  expect(check.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(check.responseBody).status).toBe('succeeded');

  const map = await sendChat(page, 'plot population density map');
  expect(map.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(map.responseBody).status).toBe('succeeded');
  expect(artifactRefs(map.responseBody).length).toBeGreaterThan(0);

  await selectFirstArtifact(page);
  const followup = await sendChat(page, '这个结果说明什么');
  const context = followup.requestBody.frontend_context || {};
  expect(context.selected_artifact_id).toBeTruthy();
  expect(['answer_only', 'builtin', 'deterministic_context', 'coordinated_workflow', 'clarification']).toContain(followup.responseBody.mode);
});

test('real backend browser flow uploads CSV and runs table-to-points map workflow', async ({ page }) => {
  await register(page, 'csv');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixture(page, 'e2e_points.csv');

  const map = await sendChat(page, 'plot population density map');
  expect(map.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(map.responseBody).status).toBe('succeeded');
  expect(artifactRefs(map.responseBody).length).toBeGreaterThan(0);
  const steps = (presentation(map.responseBody).executed_steps || []) as Array<Record<string, unknown>>;
  expect(steps.some((item) => item.tool_name === 'table_to_points')).toBeTruthy();

  await selectFirstArtifact(page);
  const followup = await sendChat(page, '这个结果说明什么');
  const context = followup.requestBody.frontend_context || {};
  expect(context.selected_artifact_id).toBeTruthy();
  expect(['answer_only', 'deterministic_context', 'coordinated_workflow', 'clarification', 'builtin']).toContain(followup.responseBody.mode);
});

test('real backend core GIS flow generates DEM slope and aspect artifacts', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  await register(page, 'dem');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixture(page, 'e2e_projected_dem.tif');

  const result = await sendChat(page, '计算该 DEM 的坡度和坡向，使用角度制。');
  expect(result.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(result.responseBody).status).toBe('succeeded');
  expect(executedSteps(result.responseBody).some((item) => item.tool_name === 'dem_terrain_derivatives')).toBeTruthy();
  expect(artifactRefs(result.responseBody).filter((item) => String(item.type) === 'raster')).toHaveLength(2);
  expect(mapLayerRefs(result.responseBody)).toHaveLength(2);
  await expect(page.getByTestId('task-status-card').last()).toBeVisible();
  await expect(page.getByTestId('result-groups').last()).toBeVisible();
  await expect(page.getByTestId('result-group-recommended').last()).toContainText('推荐查看');
  await expectArtifactDownload(page, result.responseBody, artifactRefs(result.responseBody)[0]);
  await deleteSessionAndExpectArtifactBlocked(page, result.responseBody, artifactRefs(result.responseBody)[0], mapLayerRefs(result.responseBody));
  expect(problems).toEqual([]);
});

test('real backend core GIS flow calculates NDVI from explicit red and nir rasters', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  await register(page, 'ndvi');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixtures(page, ['e2e_red_reflectance.tif', 'e2e_nir_reflectance.tif']);

  const result = await sendChat(page, '使用 e2e_red_reflectance 作为红光、e2e_nir_reflectance 作为近红外计算 NDVI。');
  expect(result.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(result.responseBody).status).toBe('succeeded');
  expect(executedSteps(result.responseBody).some((item) => item.tool_name === 'raster_algebra')).toBeTruthy();
  expect(artifactRefs(result.responseBody).some((item) => String(item.title || '').toLowerCase().includes('ndvi'))).toBeTruthy();
  expect(mapLayerRefs(result.responseBody).some((item) => String(item.name || '').toLowerCase().includes('ndvi'))).toBeTruthy();
  const highlights = (presentation(result.responseBody).result_highlights || []) as string[];
  expect(highlights.join(' ')).toContain('result_dataset=ndvi');
  await expectArtifactDownload(page, result.responseBody, artifactRefs(result.responseBody)[0]);
  expect(problems).toEqual([]);
});

test('real backend core GIS flow samples raster values to uploaded stations', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  await register(page, 'sample');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixtures(page, ['e2e_station_points.csv', 'e2e_feature_raster.tif']);

  const result = await sendChat(page, '提取每个站点的栅格值并生成可下载表格。');
  expect(result.responseBody.mode).toBe('coordinated_workflow');
  expect(presentation(result.responseBody).status).toBe('succeeded');
  const tools = executedSteps(result.responseBody).map((item) => item.tool_name);
  expect(tools).toContain('table_to_points');
  expect(tools).toContain('extract_raster_values_to_points');
  expect(tableRefs(result.responseBody).length).toBeGreaterThan(0);
  expect(artifactRefs(result.responseBody).length).toBeGreaterThan(0);
  await expectArtifactDownload(page, result.responseBody, artifactRefs(result.responseBody)[0]);
  expect(problems).toEqual([]);
});

test('real backend core GIS failure cases stay safe and Chinese', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  await register(page, 'failure');
  await openWorkspace(page);
  await enableToolMode(page);

  await uploadFixture(page, 'e2e_geo_dem.tif');
  const dem = await sendChat(page, '计算该 DEM 的坡度和坡向，使用角度制。');
  expect(['failed', 'blocked']).toContain(String(presentation(dem.responseBody).status));
  expect(artifactRefs(dem.responseBody)).toHaveLength(0);
  expect(String(dem.responseBody.reply)).toMatch(/投影|坐标|重投影|DEM/);

  await page.getByTestId('chat-new-session-compact').first().click();
  await enableToolMode(page);
  await uploadFixtures(page, ['e2e_projected_dem.tif', 'e2e_feature_raster.tif']);
  const ndvi = await sendChat(page, '计算 NDVI。');
  expect(['clarification', 'coordinated_workflow']).toContain(String(ndvi.responseBody.mode));
  expect(artifactRefs(ndvi.responseBody)).toHaveLength(0);
  expect(String(ndvi.responseBody.reply)).toMatch(/红光|近红外|明确/);

  await page.getByTestId('chat-new-session-compact').first().click();
  await enableToolMode(page);
  await uploadFixtures(page, ['e2e_feature_raster.tif', 'e2e_no_overlap_boundary.geojson']);
  const clip = await sendChat(page, '用边界裁剪这个栅格。');
  expect(['failed', 'blocked']).toContain(String(presentation(clip.responseBody).status));
  expect(artifactRefs(clip.responseBody)).toHaveLength(0);
  expect(String(clip.responseBody.reply)).not.toMatch(/Traceback|session_id|user_id|raw dict|workspace/i);
  expect(problems).toEqual([]);
});

test('real backend chat history remains stable across refresh and session switches', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  const deleteRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/chat\/sessions\/(delete|clear)/.test(request.url())) deleteRequests.push(request.url());
  });
  await register(page, 'chat-stability');
  await openWorkspace(page);

  await sendChat(page, '你好');
  await sendChat(page, '什么是 GIS？');
  await sendChat(page, '如何上传 shp？');
  await sendChat(page, '下载闪电河流域 LST');
  await uploadFixture(page, 'e2e_points.csv');
  const lastTurn = await sendChat(page, 'plot population density map');
  const originalSessionId = String(lastTurn.responseBody.current_session_id || '');

  const expectedTexts = ['你好', 'GIS', '上传 SHP', '闪电河流域', 'plot population density map'];
  for (const text of expectedTexts) {
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
  }

  await page.reload();
  await openWorkspace(page);
  await expect(page.getByTestId('chat-input')).toBeVisible();
  for (const text of expectedTexts) {
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
  }

  await page.getByTestId('chat-new-session-compact').first().click();
  await expect(page.getByTestId('chat-empty-state')).toBeVisible();
  await page.locator('select.chat-compact-select').first().selectOption(originalSessionId);
  for (const text of expectedTexts) {
    await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
  }
  expect(deleteRequests).toEqual([]);
  expect(problems).toEqual([]);
});

test('real backend artifact download button resolves artifact_id and downloads a non-empty file', async ({ page }) => {
  const problems = captureConsoleProblems(page);
  await register(page, 'artifact-button');
  await openWorkspace(page);
  await enableToolMode(page);
  await uploadFixture(page, 'e2e_counties.geojson');

  const result = await sendChat(page, 'plot population density map');
  expect(presentation(result.responseBody).status).toBe('succeeded');
  expect(artifactRefs(result.responseBody).length).toBeGreaterThan(0);

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('artifact-download').first().click(),
  ]);
  const suggested = download.suggestedFilename();
  expect(suggested.length).toBeGreaterThan(0);
  const pathOnDisk = await download.path();
  expect(pathOnDisk).toBeTruthy();
  const response = await page.request.get(`/api/artifacts/${encodeURIComponent(String(artifactRefs(result.responseBody)[0].artifact_id || ''))}/download?session_id=${encodeURIComponent(String(result.responseBody.current_session_id || ''))}`);
  expect(response.status()).toBe(200);
  expect((await response.body()).byteLength).toBeGreaterThan(0);
  expect(problems).toEqual([]);
});
