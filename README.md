# GIS Agent Web

Web-only GIS agent for local geospatial analysis, commercial download jobs, and GSCloud scene/table downloads.

## What This Project Provides

- React + Vite web UI in `ui_next/`
- FastAPI backend in `api_server.py`
- Commercial user, quota, payment simulation, platform account pool, and download job service
- GSCloud automation for DEM, Landsat 8, Sentinel-2, MODIS NDVI/LST/EVI, and MOD021KM products
- Workspace import/export, local library indexing, and map-ready artifact listing

## Requirements

- Python 3.11+ recommended
- Node.js 20+ recommended
- Playwright browsers for GSCloud automation
- Optional GIS packages such as `rasterio`, `geopandas`, and related native dependencies for advanced validation and map processing

## Setup

```powershell
cd e:\agent\gis_agent_web_only_builtin_shp_v1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium

cd ui_next
npm install
cd ..
```

Copy `.env.example` to `.env` and fill in only local/private values:

```powershell
Copy-Item .env.example .env
```

Important values:

- `APP_SECRET_KEY`: required for encrypting saved credentials. Generate one with the commercial tool or a Fernet key.
- `GIS_AGENT_ENV=production`: disables implicit workspace secret creation unless `GIS_AGENT_ALLOW_WORKSPACE_SECRET_FILE=1` is explicitly set.
- `GIS_AGENT_ADMIN_TOKEN`: optional admin token for protected administrative/debug actions. Set it outside Git in production.
- `GIS_AGENT_ENABLE_MOCK_PAYMENT`: keep `0` by default. Set `1` only for local demos where logged-in users may trigger simulated payments.
- `GIS_AGENT_COOKIE_SECURE=1`: use when serving the API over HTTPS so browser session cookies are marked secure.
- `GSCLOUD_PLATFORM_USERNAME` / `GSCLOUD_PLATFORM_PASSWORD`: optional backend platform account bootstrap.
- `GSCLOUD_PLATFORM_STORAGE_STATE`: optional path to a Playwright `storage_state.json`.
- `TIANDITU_TOKEN`: optional Tianditu basemap token.

Do not commit `.env`, `secrets/`, `workspace/`, or any `storage_state` / cookie files.

## Run

Backend:

```powershell
.\start_backend_api.ps1
```

Frontend:

```powershell
.\start_web_ui.ps1
```

Default frontend URL is usually `http://localhost:5173`. The backend listens on `http://127.0.0.1:8765`.

## Diagnostics

Run the local environment check before debugging download issues:

```powershell
.\scripts\doctor.ps1
```

The doctor checks the project `.venv`, key Python packages, `.env`, backend reachability, frontend dependencies, and GSCloud `storage_state` presence.

## LLM Configuration And Deployment Check

The backend supports OpenAI-compatible providers through one unified LLM configuration layer. Existing `ZAI_*` variables still work.

Common local settings:

```env
LLM_PROVIDER=zai
LLM_MODEL=glm-4.5-air
LLM_API_KEY_ENV=ZAI_API_KEY
LLM_BASE_URL=https://api.z.ai/api/paas/v4/
LLM_TIMEOUT=60
LLM_MAX_RETRIES=2
ENABLE_LLM_INTENT_CLASSIFIER=0
FALLBACK_TO_RULE_CLASSIFIER=1
ZAI_API_KEY=
```

For OpenAI-compatible deployments, use:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY_ENV=OPENAI_API_KEY
OPENAI_API_KEY=
```

Check config without making a network request:

```powershell
python scripts\check_llm_health.py
```

Check the real provider during deployment:

```powershell
python scripts\check_llm_health.py --network
```

Use strict mode in deployment gates when degraded rule-only fallback should fail the release:

```powershell
python scripts\check_llm_health.py --strict
python scripts\check_llm_health.py --network --strict
```

The API also exposes:

```text
GET /api/llm/health?network=false
GET /api/llm/health?network=true
```

If no API key is configured and `FALLBACK_TO_RULE_CLASSIFIER=1`, the semantic intent classifier falls back to deterministic rules and the health result is `degraded` instead of crashing. The default CLI exits successfully for `ok` and `degraded` so local rule-only development can continue; `--strict` exits non-zero unless the provider is fully `ok`. Requests that require the main LLM agent still need a valid provider key. Health errors report the missing env var name, never the secret value.

Common fixes:

- `UNSUPPORTED_PROVIDER`: set `LLM_PROVIDER` to `zai`, `openai`, or `fake`.
- `MODEL_REQUIRED`: set `LLM_MODEL` or the legacy provider model variable.
- `API_KEY_MISSING`: set the env var named by `LLM_API_KEY_ENV`, such as `ZAI_API_KEY` or `OPENAI_API_KEY`.
- `BASE_URL_INVALID`: use an `http://` or `https://` provider endpoint.

## GSCloud Login State

GSCloud automation needs a valid Playwright storage state. For platform accounts, use the login workflow in the app or set `GSCLOUD_PLATFORM_STORAGE_STATE` to a local JSON file.

Preflight without downloading:

```powershell
python scripts\verify_gscloud_scene_download.py --product-key landsat8_oli_tirs --storage-state path\to\gscloud_storage_state.json --download-dir workspace\gscloud_download_verification --max-pages 1 --region 成都
```

Add `--execute-download` only when you intentionally want to download a file.

## Shapefile Export Notes

Vector exports requested as `.shp` are delivered as a `.zip` package. A Shapefile is a multi-file format, so the package keeps `.shp`, `.shx`, `.dbf`, `.prj` when CRS is available, `.cpg`, and any other writer sidecar files together.

The export tool writes UTF-8 and includes a `.cpg` file. ESRI Shapefile/DBF still limits field names to 10 characters, so long columns such as `population_density` may be truncated by the GIS writer. The structured `ToolResult.warnings` field reports this with `SHAPEFILE_FIELD_NAME_TRUNCATION`; use GeoJSON when full field names must be preserved.

Export paths are restricted to the workspace. The API rejects output paths that escape the workspace and Shapefile zip members are written with local filenames only, avoiding archive path traversal.

## Tests

Python:

```powershell
python -m unittest discover tests
```

Frontend:

```powershell
cd ui_next
npm test
npm run build
```

Run a focused frontend test when debugging one area:

```powershell
npm run test:analysis-model-results
npm run test:analysis-panel
npm run test:chat-message-content
npm run test:chat-panel-experience
npm run test:chat-persistence
npm run test:layer-policy
npm run test:local-library
npm run test:map-upgrades
npm run test:product-console
npm run test:research-workflow
npm run test:task-outcome-experience
```

Smoke test with both servers running:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_smoke.py
```

GitHub Actions runs Python tests, frontend build/checks, doctor, and an end-to-end smoke test.

## Job Safety

- Platform account jobs reserve quota before expensive work starts.
- Failed or canceled jobs release reserved quota.
- Completed jobs mark the reservation as charged without double-counting.
- Running or waiting jobs cannot be deleted directly; cancel first, then delete the record.
- Retry creates a new job from the failed/canceled/waiting job and links it with `retried_from_job_id`.

## Repository Hygiene

The repository intentionally ignores:

- `.env` and `.env.*`
- `secrets/`
- `workspace/`
- `local_library/`
- Playwright `storage_state` / cookie JSON
- frontend `node_modules/` and `dist/`
- Python and TypeScript caches
