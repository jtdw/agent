import { expect, test, type Page } from '@playwright/test';

type ChatAskBody = {
  prompt?: string;
  frontend_context?: Record<string, unknown>;
};

const SESSION_ID = 'session_test';

const dashboard = {
  workdir: 'mock-workspace',
  dataset_type_counts: { table: 1, vector: 1, raster: 0, document: 0 },
  runtime_status: { phase: 'completed', label: 'ready', progress: 100 },
  artifacts: [
    {
      name: 'soil_map.png',
      path: 'plots/soil_map.png',
      type: 'chart',
      download_url: '/api/files/artifact?path=plots%2Fsoil_map.png',
    },
  ],
  analysis: {
    metrics_dataset: 'xgb_metrics',
    metric_rows: [{ model: 'XGBoost', R: 0.82, RMSE: 0.11, NSE: 0.73 }],
  },
  model_results: [
    {
      model_result_id: 'model_result_xgb_001',
      model: 'XGBoost',
      output_prefix: 'xgb_soil',
      metrics_dataset: 'xgb_metrics',
      metrics: { R: 0.82, RMSE: 0.11, NSE: 0.73 },
      artifacts: [
        {
          name: 'feature_importance.png',
          path: 'models/feature_importance.png',
          download_url: '/api/files/artifact?path=models%2Ffeature_importance.png',
        },
      ],
    },
  ],
  latest_pipeline: {
    run_id: 'run_001',
    pipeline_name: 'Mock analysis',
    status: 'completed',
    steps: [{ step_name: 'train', status: 'completed', output_summary: 'Mock model trained.' }],
  },
};

const resultPanel = {
  has_results: true,
  title: 'Mock result',
  files: [
    {
      label: 'soil_map.png',
      path: 'plots/soil_map.png',
      download_url: '/api/files/artifact?path=plots%2Fsoil_map.png',
      kind: 'chart',
    },
  ],
  recommendations: ['Explain the current map and validate outliers.'],
};

async function setupMockApi(page: Page, askBodies: ChatAskBody[]) {
  page.context().on('page', (popup) => void popup.close().catch(() => {}));

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === '/api/auth/me') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: true,
          user: { user_id: 'u_test', email: 'e2e@example.com', plan: 'basic', status: 'active' },
          session_id: 'auth_session',
        }),
      });
      return;
    }

    if (path === '/api/chat/sessions') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [{ session_id: SESSION_ID, title: 'E2E session' }],
          current_session_id: SESSION_ID,
          messages: [],
        }),
      });
      return;
    }

    if (path === '/api/workspace/dashboard') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(dashboard) });
      return;
    }

    if (path === '/api/downloads/jobs') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ jobs: [] }) });
      return;
    }

    if (path === '/api/tianditu/config') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ enabled: false, subdomains: [], tile_url_templates: {}, capabilities: [] }),
      });
      return;
    }

    if (path === '/api/map/stations') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          source: 'mock',
          source_name: 'mock stations',
          count: 1,
          bounds: [116.17, 41.77, 116.19, 41.79],
          center: [116.18, 41.78],
          stations: [
            {
              id: 'station_001',
              station_id: 'station_001',
              name: 'Station A',
              longitude: 116.18,
              latitude: 41.78,
              lng: 116.18,
              lat: 41.78,
              sample_count: 12,
              mean_sm: 0.42,
              elevation_m: 100,
              source_file: 'mock.csv',
            },
          ],
        }),
      });
      return;
    }

    if (path === '/api/map/layers') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          layers: [
            {
              id: 'soil_points',
              name: 'Soil points',
              type: 'vector',
              kind: 'soil',
              bounds: [116.17, 41.77, 116.19, 41.79],
              feature_count: 1,
              geojson: {
                type: 'FeatureCollection',
                features: [
                  {
                    type: 'Feature',
                    id: 'feature_001',
                    properties: {
                      id: 'feature_001',
                      name: 'Anomaly A',
                      value: 0.88,
                      token: 'must_not_be_sent',
                      raw_content: 'x'.repeat(5000),
                      html: '<b>must not be sent</b>',
                    },
                    geometry: { type: 'Point', coordinates: [116.18, 41.78] },
                  },
                ],
              },
            },
          ],
        }),
      });
      return;
    }

    if (path === '/api/chat/ask') {
      const body = route.request().postDataJSON() as ChatAskBody;
      askBodies.push(body);
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          reply: 'ok',
          current_session_id: SESSION_ID,
          sessions: [{ session_id: SESSION_ID, title: 'E2E session' }],
          messages: [
            { message_id: 1, role: 'user', content: body.prompt || '' },
            { message_id: 2, role: 'assistant', content: 'ok' },
          ],
          result_panel: resultPanel,
        }),
      });
      return;
    }

    if (path === '/api/files/artifact') {
      await route.fulfill({ contentType: 'text/plain', body: 'mock artifact' });
      return;
    }

    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
}

async function openWorkspace(page: Page) {
  await page.goto('/');
  await page.getByTestId('open-map-workspace').first().click();
  await expect(page.getByTestId('chat-input')).toBeVisible();
}

async function sendChat(page: Page, text: string) {
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
}

function latestAsk(askBodies: ChatAskBody[]) {
  expect(askBodies.length).toBeGreaterThan(0);
  return askBodies[askBodies.length - 1];
}

test('sends selected artifact context after result item click', async ({ page }) => {
  const askBodies: ChatAskBody[] = [];
  await setupMockApi(page, askBodies);
  await openWorkspace(page);

  await page.getByTestId('analysis-panel-open').click();
  await page.getByTestId('analysis-artifact-item').filter({ hasText: 'soil_map.png' }).click();
  await page.getByTestId('analysis-panel-close').click();
  await sendChat(page, '这个结果说明什么');

  const context = latestAsk(askBodies).frontend_context || {};
  expect(context.selected_artifact_id || context.selected_artifact_path).toBeTruthy();
  expect(context.selected_artifact_path).toContain('plots%2Fsoil_map.png');
});

test('sends selected map feature context after station marker click', async ({ page }) => {
  const askBodies: ChatAskBody[] = [];
  await setupMockApi(page, askBodies);
  await openWorkspace(page);

  await page.getByTestId('map-station-marker').first().click();
  await sendChat(page, '这个区域为什么异常');

  const context = latestAsk(askBodies).frontend_context || {};
  const properties = (context.selected_feature_properties || {}) as Record<string, unknown>;
  expect(context.selected_feature_id || properties.station_id).toBeTruthy();
  expect(JSON.stringify(properties).length).toBeLessThanOrEqual(4096);
  for (const forbiddenKey of ['token', 'raw_content', 'file', 'html', 'base64']) {
    expect(Object.keys(properties)).not.toContain(forbiddenKey);
  }
});

test('sends selected model result context after model card click', async ({ page }) => {
  const askBodies: ChatAskBody[] = [];
  await setupMockApi(page, askBodies);
  await openWorkspace(page);

  await page.getByTestId('analysis-panel-open').click();
  await page.getByTestId('analysis-model-result').click();
  await page.getByTestId('analysis-panel-close').click();
  await sendChat(page, '模型效果怎么样');

  const context = latestAsk(askBodies).frontend_context || {};
  expect(context.selected_model_result_id).toBeTruthy();
  expect(context.selected_model_result_id).toBe('model_result_xgb_001');
});
