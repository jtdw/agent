import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, '..');
const realBackendWorkdir = path.resolve(__dirname, 'test-results', 'real-backend-workspace');

export default defineConfig({
  testDir: './e2e',
  testMatch: /real-backend-chat\.spec\.ts/,
  timeout: 90_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location ..; .\\.venv\\Scripts\\python.exe -m uvicorn api_server:app --host 127.0.0.1 --port 8765"',
      url: 'http://127.0.0.1:8765/api/status',
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        GIS_AGENT_WORKDIR: realBackendWorkdir,
        LLM_PROVIDER: 'fake',
        ENABLE_LLM_INTENT_CLASSIFIER: '0',
        GIS_AGENT_ENABLE_LLM_INTENT: '0',
        FALLBACK_TO_RULE_CLASSIFIER: '1',
        GIS_AGENT_COOKIE_SECURE: '0',
        APP_SECRET_KEY: 'playwright-real-backend-test-secret',
        PYTHONPATH: workspaceRoot,
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5174',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
