import { expect, test, type Page } from '@playwright/test';

async function setupChatUpgradeMock(page: Page) {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/auth/me') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ authenticated: true, user: { user_id: 'u_test', email: 'e2e@example.com', plan: 'basic' } }) });
      return;
    }
    if (path === '/api/chat/sessions') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ sessions: [{ session_id: 'session_test', title: 'Chat upgrade' }], current_session_id: 'session_test', messages: [] }) });
      return;
    }
    if (path === '/api/chat/models') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ session_id: 'session_test', route_mode: 'auto', selected_model: 'auto', models: [] }) });
      return;
    }
    if (path === '/api/workspace/dashboard') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ summary: '', datasets: [], artifacts: [], activity: [], dataset_type_counts: {}, runtime_status: {}, capability_groups: {}, suggestions: [] }) });
      return;
    }
    if (path === '/api/downloads/jobs') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ jobs: [] }) });
      return;
    }
    if (path === '/api/tianditu/config') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ enabled: false, subdomains: [], tile_url_templates: {}, capabilities: [] }) });
      return;
    }
    if (path === '/api/map/stations') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ source: 'mock', source_name: 'mock', count: 0, bounds: [0, 0, 0, 0], center: [0, 0], stations: [] }) });
      return;
    }
    if (path === '/api/map/layers') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ layers: [] }) });
      return;
    }
    if (path === '/api/chat/ask') {
      const body = route.request().postDataJSON() as { prompt?: string };
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          reply: 'done',
          current_session_id: 'session_test',
          sessions: [{ session_id: 'session_test', title: 'Chat upgrade' }],
          messages: [
            { message_id: 1, role: 'user', content: body.prompt || '' },
            {
              message_id: 2,
              role: 'assistant',
              content: '已生成结果。\n\n```python\nprint("ok")\n```',
              meta: {
                artifacts: [
                  {
                    artifact_id: 'artifact_csv',
                    filename: 'result.csv',
                    type: 'csv',
                    kind: 'csv',
                    mime_type: 'text/csv',
                    size_bytes: 12,
                    created_at: '2026-06-14T10:00:00',
                    source: { tool_name: 'export_dataset' },
                    download_url: '/api/artifacts/artifact_csv/download',
                  },
                ],
              },
            },
          ],
        }),
      });
      return;
    }
    if (path === '/api/artifacts/artifact_csv/download') {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/csv', 'content-disposition': 'attachment; filename="result.csv"' },
        body: 'a,b\n1,2\n',
      });
      return;
    }
    if (path === '/api/files/artifact') {
      await route.fulfill({
        status: 410,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { error_code: 'LEGACY_ARTIFACT_DOWNLOAD_DISABLED', message: 'Legacy path downloads are disabled.' } }),
      });
      return;
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
}

async function openChat(page: Page) {
  await page.goto('/');
  await page.getByTestId('open-map-workspace').first().click();
  await expect(page.getByTestId('chat-input').first()).toBeVisible();
}

test('chat artifact card downloads generated result', async ({ page, browserName }) => {
  await setupChatUpgradeMock(page);
  await openChat(page);
  await page.getByTestId('chat-input').first().fill('生成结果');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('artifact-download-card')).toContainText('result.csv');
  if (browserName === 'firefox') {
    await expect(page.getByTestId('artifact-download')).toBeEnabled();
    return;
  }
  const download = page.waitForEvent('download');
  await page.getByTestId('artifact-download').click({ force: true });
  expect((await download).suggestedFilename()).toBe('result.csv');
});
test('chat message and code block can be copied', async ({ page, browserName }) => {
  const reactErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('Maximum update depth exceeded')) reactErrors.push(message.text());
  });
  await setupChatUpgradeMock(page);
  await openChat(page);
  await page.getByTestId('chat-input').first().fill('生成代码');
  await page.getByTestId('chat-send').click();
  await page.getByTestId('copy-message').click();
  if (browserName === 'chromium') {
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('已生成结果');
  } else {
    await expect(page.getByTestId('copy-message')).toContainText('已复制');
  }
  await page.getByTestId('copy-code').click();
  if (browserName === 'chromium') {
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('print("ok")');
  } else {
    await expect(page.getByTestId('copy-code')).toContainText('已复制');
  }
  expect(reactErrors).toEqual([]);
});

test('legacy path download endpoint is disabled', async ({ page }) => {
  await setupChatUpgradeMock(page);
  await page.goto('/');
  const response = await page.evaluate(async () => {
    const result = await fetch('/api/files/artifact?path=workspace.db');
    return { status: result.status, body: await result.json() };
  });
  expect(response.status).toBe(410);
  expect(response.body.detail.error_code).toBe('LEGACY_ARTIFACT_DOWNLOAD_DISABLED');
});

test('mobile composer is visible and editable at 390x844', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupChatUpgradeMock(page);
  await openChat(page);
  const composer = page.getByTestId('chat-input').first();
  await composer.fill('移动端输入');
  const box = await composer.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  const dimensions = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width);
});

test('floating chat uses compact controls without overlapping copy actions', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupChatUpgradeMock(page);
  await openChat(page);
  await expect(page.getByTestId('floating-chat-toolbar')).toBeVisible();
  await expect(page.getByTestId('floating-chat-delete')).toBeVisible();
  await expect(page.getByTestId('chat-voice')).toBeVisible();

  await page.getByTestId('chat-input').fill('生成代码');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('copy-message')).toBeVisible();

  const geometry = await page.evaluate(() => {
    const actions = document.querySelector('[data-testid="chat-message-actions"]')?.getBoundingClientRect();
    const markdown = document.querySelector('.chat-message-renderer .chat-markdown')?.getBoundingClientRect();
    const toolbar = document.querySelector('[data-testid="floating-chat-toolbar"]')?.getBoundingClientRect();
    const composer = document.querySelector('[data-testid="chat-composer"]')?.getBoundingClientRect();
    return {
      actionsTop: actions?.top ?? 0,
      markdownBottom: markdown?.bottom ?? 0,
      toolbarWidth: toolbar?.width ?? 0,
      composerCenterDelta: composer ? Math.abs((composer.left + composer.right) / 2 - window.innerWidth / 2) : 999,
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    };
  });

  expect(geometry.actionsTop).toBeGreaterThanOrEqual(geometry.markdownBottom);
  expect(geometry.toolbarWidth).toBeLessThanOrEqual(390);
  expect(geometry.composerCenterDelta).toBeLessThan(8);
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.viewportWidth);
});
