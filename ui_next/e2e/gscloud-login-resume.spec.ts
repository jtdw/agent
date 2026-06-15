import { expect, test, type Page } from '@playwright/test';

async function setupGSCloudMock(page: Page) {
  let resumed = false;
  let jobPolls = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/auth/me') return json({ authenticated: true, user: { user_id: 'u_test', email: 'user@example.com', plan: 'basic' } });
    if (path === '/api/chat/sessions') return json({ sessions: [{ session_id: 's1', title: 'DEM 下载' }], current_session_id: 's1', messages: [] });
    if (path === '/api/chat/models') return json({ session_id: 's1', route_mode: 'auto', selected_model: 'auto', models: [] });
    if (path === '/api/workspace/dashboard') return json({ datasets: [], artifacts: [], activity: [], dataset_type_counts: {}, runtime_status: {} });
    if (path === '/api/map/stations') return json({ count: 0, stations: [], bounds: [0, 0, 0, 0], center: [0, 0] });
    if (path === '/api/map/layers') return json({ layers: [] });
    if (path === '/api/tianditu/config') return json({ enabled: false, tile_url_templates: {} });
    if (path === '/api/data-sources/gscloud/status') return json({ provider: 'gscloud', logged_in: false, account_mode: 'own', storage_state_exists: false, health_status: 'missing_storage_state', user_message: '需要登录地理空间数据云账号。' });
    if (path === '/api/data-sources/gscloud/login/start') return json({ provider: 'gscloud', login_session_id: 'login_mock', state: 'BROWSER_OPEN', user_message: '已打开登录窗口。', poll_interval_ms: 50 });
    if (path === '/api/data-sources/gscloud/login/complete') return json({ provider: 'gscloud', logged_in: true, account_mode: 'own', storage_state_exists: true, health_status: 'healthy', user_message: '已登录', pending: false, waiting_jobs: [{ job_id: 'job_dem', status: 'waiting_login' }] });
    if (path === '/api/chat/ask') return json({
      reply: '这个数据源需要登录地理空间数据云账号后才能下载。任务尚未开始下载。',
      job: { job_id: 'job_dem', status: 'waiting_login' },
      action_required: { type: 'login_required', provider: 'gscloud', job_id: 'job_dem' },
      current_session_id: 's1',
      sessions: [{ session_id: 's1', title: 'DEM 下载' }],
      messages: [
        { message_id: 1, role: 'user', content: '帮我下载当前研究区的 DEM' },
        { message_id: 2, role: 'assistant', content: '需要登录地理空间数据云账号。', meta: { action_required: { type: 'login_required', provider: 'gscloud', job_id: 'job_dem' } } },
      ],
    });
    if (path === '/api/download-jobs/job_dem/resume') {
      resumed = true;
      return json({ job: { job_id: 'job_dem', status: 'running' }, auto_started: true, reason: 'started' });
    }
    if (path === '/api/downloads/jobs') {
      jobPolls += 1;
      return json({ jobs: resumed && jobPolls > 1 ? [{ job_id: 'job_dem', status: 'completed', artifacts: [{ artifact_id: 'artifact_dem', filename: 'dem.tif', type: 'dem', mime_type: 'image/tiff', size_bytes: 1024, download_url: '/api/artifacts/artifact_dem/download' }] }] : [{ job_id: 'job_dem', status: resumed ? 'running' : 'waiting_login' }] });
    }
    return json({ ok: true });
  });
}

test('GSCloud login resumes DEM job and shows artifact card', async ({ page }) => {
  await setupGSCloudMock(page);
  await page.goto('/');
  await page.getByTestId('open-map-workspace').first().click();
  await page.getByTestId('chat-input').fill('帮我下载当前研究区的 DEM');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('gscloud-login-dialog')).toBeVisible();
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('button', { name: '继续下载' })).toBeVisible();
  await page.getByRole('button', { name: '继续下载' }).click();
  await expect(page.getByTestId('artifact-download-card')).toContainText('dem.tif', { timeout: 10_000 });
});

test('product console settings shows GSCloud account login entry', async ({ page }) => {
  await setupGSCloudMock(page);
  await page.goto('/');

  await page.getByRole('button', { name: '设置', exact: true }).click();

  await expect(page.getByRole('heading', { name: '我的数据源账号' })).toBeVisible();
  await expect(page.getByTestId('gscloud-account-panel')).toBeVisible();
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
});
