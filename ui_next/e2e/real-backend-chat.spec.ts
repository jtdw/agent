import { expect, test, type Page, type APIResponse } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

type ChatAskBody = {
  prompt?: string;
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

async function uploadFixture(page: Page, name: string) {
  const [response] = await Promise.all([
    page.waitForResponse((item) => item.url().includes('/api/files/upload') && item.status() === 200),
    page.getByTestId('chat-file-input').setInputFiles(fixturePath(name)),
  ]);
  const body = await response.json();
  expect(body.ok).toBeTruthy();
  expect(body.count).toBeGreaterThan(0);
}

async function sendChat(page: Page, text: string): Promise<{ requestBody: ChatAskBody; responseBody: Record<string, unknown>; response: APIResponse }> {
  const responsePromise = page.waitForResponse((response) => response.url().includes('/api/chat/ask') && response.request().method() === 'POST');
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const requestBody = response.request().postDataJSON() as ChatAskBody;
  const responseBody = await response.json();
  expect(String(responseBody.reply || '').length).toBeGreaterThan(0);
  return { requestBody, responseBody, response };
}

function presentation(body: Record<string, unknown>) {
  return (body.presentation_result || {}) as Record<string, unknown>;
}

function artifactRefs(body: Record<string, unknown>) {
  return ((presentation(body).artifact_refs || []) as Array<Record<string, unknown>>);
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
  expect(['builtin', 'deterministic_context', 'coordinated_workflow', 'clarification']).toContain(followup.responseBody.mode);
});

test('real backend browser flow uploads CSV and runs table-to-points map workflow', async ({ page }) => {
  await register(page, 'csv');
  await openWorkspace(page);
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
  expect(['deterministic_context', 'coordinated_workflow', 'clarification', 'builtin']).toContain(followup.responseBody.mode);
});
