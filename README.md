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

Default frontend URL is usually `http://localhost:5173`.

## GSCloud Login State

GSCloud automation needs a valid Playwright storage state. For platform accounts, use the login workflow in the app or set `GSCLOUD_PLATFORM_STORAGE_STATE` to a local JSON file.

Preflight without downloading:

```powershell
python scripts\verify_gscloud_scene_download.py --product-key landsat8_oli_tirs --storage-state path\to\gscloud_storage_state.json --download-dir workspace\gscloud_download_verification --max-pages 1 --region 成都
```

Add `--execute-download` only when you intentionally want to download a file.

## Tests

Python:

```powershell
python -m unittest discover tests
```

Frontend:

```powershell
cd ui_next
npm run build
npm run test:layer-policy
npm run test:local-library
npm run test:map-upgrades
npm run test:research-workflow
npm run test:analysis-panel
```

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

