# GIS Agent Cleanup Migration Plan

Generated for dry-run review on 2026-06-13. No file has been moved or deleted.

## Safety Contract

- Archive destination: `E:\agent\test\gis_agent_web_only_builtin_shp_v1\<timestamp>\`.
- Preserve each source path relative to the project root.
- Never move `.git`, `.env`, `.venv`, current source, current tests, or unsure items.
- Never overwrite an existing target. Stop on a collision, missing approved source, path escape, or move failure.
- Sensitive file contents must not appear in console output, Markdown, or the future manifest.
- This phase creates the plan and dry-run script only. Execution requires a separate confirmation.

## A. Keep In Place

| Path | Reason |
| --- | --- |
| `.git/`, `.github/` | Repository identity and active CI workflows. |
| `.env`, `.env.example`, `.gitignore` | Real private configuration, safe example, and repository hygiene rules. |
| `.venv/` | Existing GIS Python environment retained for stable verification. |
| `README.md`, `requirements.txt` | Active run documentation and Python dependencies. |
| `api_server.py`, `app.py` | Active FastAPI application and launcher. |
| `start_backend_api.ps1`, `start_web_ui.ps1` | Supported startup scripts. |
| `core/` | Agent, ToolResult contracts, workflows, conversations, LLM configuration, GIS tools, commercial services, and download workers. |
| `tests/` | Python regression tests and small fixtures, including the cleanup dry-run safety test. |
| `scripts/` | Diagnostics, health checks, smoke checks, account tooling, and dry-run script. |
| `ui_next/src/`, `ui_next/public/`, `ui_next/index.html` | Active React application and referenced static asset. |
| `ui_next/package.json`, `ui_next/package-lock.json` | Frontend scripts, dependencies, and reproducible lock file. |
| `ui_next/tests/`, `ui_next/e2e/` | Frontend unit and real-backend workflow coverage. |
| `ui_next/*.config.*`, `ui_next/tsconfig.json` | Vite, TypeScript, Tailwind, PostCSS, and Playwright configuration. |
| `workspace/local_library/` | Active built-in GIS library selected by `.env`; required for bundled boundaries and station data. |

All existing modified and untracked source/test files remain in place, including `ui_next/tests/hoverStability.test.mjs`.

## B. Move After Confirmation

| Source | Destination suffix | Reason |
| --- | --- | --- |
| `web_app.py` | `web_app.py` | Legacy Streamlit UI; active launchers, README, CI, and frontend use FastAPI + React. |
| `.streamlit/` | `.streamlit/` | Legacy UI configuration with no active launcher reference. |
| `package-lock.json` | `package-lock.json` | Empty root lock file; active lock file is under `ui_next/`. |
| `docs/superpowers/specs/` | Same relative path | Historical design records, not runtime documentation. |
| `.vscode/` | `.vscode/` | Developer-local IDE state. |
| `output/` | `output/` | Generated/empty output outside the supported workspace model. |
| Every `__pycache__/` listed by the script | Same relative path | Reproducible Python bytecode caches. |
| `ui_next/node_modules/` | Same relative path | Rebuild with `npm ci`. |
| `ui_next/dist/` | Same relative path | Rebuild with `npm run build`. |
| `ui_next/test-results/` | Same relative path | Generated Playwright output. |
| `ui_next/tsconfig.tsbuildinfo` | Same relative path | TypeScript build cache. |
| `ui_next/vite-dev.*.log` | Same relative path | Historical development logs. |

After confirmation, back up `requirements.txt` to the batch directory and remove only `streamlit>=1.55.0` because its sole remaining consumer is `web_app.py`.

## C. Sensitive Runtime Reset

Move these paths without reading or displaying their contents:

- `secrets/`
- `workspace/anonymous/`
- `workspace/users/`
- `workspace/commercial.db`
- `workspace/workspace.db`
- `workspace/commercial_secret.key`
- `workspace/domestic_auth/`
- `workspace/domestic_downloads/`
- `workspace/derived/`
- `workspace/gscloud_download_verification/`
- `workspace/verification/`
- Root workspace `uploads/`, `plots/`, `temp/`, and `exports/`
- `workspace/demo_xgboost_soil_moisture.csv`

This intentionally resets users, subscriptions, quotas, conversations, sessions, browser login state, jobs, downloads, uploads, derived outputs, model results, and artifacts. The application must recreate empty runtime databases and directories on startup. `workspace/local_library/` and `.env` remain.

## D. Unsure, Do Not Move

| Path | Reason |
| --- | --- |
| `local_library/` | Data files duplicate the active library, but its manifest and README differ; retain pending manual reconciliation. |
| `ui_next/src/components/ErrorBoundary.tsx` | No current import found, but it is a plausible application safety component. |

Static zero-import findings are not sufficient to move backend modules. In particular, `core.commercial.gscloud_*_worker` modules are launched dynamically with `python -m` and must remain. Tool registry modules and product registry modules remain because tests and runtime builders reference them.

## Execution And Manifest

After explicit confirmation, execution must:

1. Create a new timestamped batch directory and write `moved_files_manifest.json` before the first move.
2. Record source, destination, category, reason, byte size, timestamp, sensitive flag, and status for every item.
3. Move in deterministic order without overwriting; update each manifest status atomically.
4. Stop immediately on a failed item and leave completed manifest entries available for rollback.
5. Rebuild frontend dependencies with `npm ci`.
6. Leave all D items untouched.

## Verification After Migration

```powershell
python -m compileall core tests
python -m unittest discover tests
cd ui_next
npm test
npm run build
```

Then start both supported launchers, verify `/api/status`, run `scripts/e2e_smoke.py`, and run the real-backend Playwright flow for registration, upload, inspection, mapping, artifact selection, and follow-up explanation. Move validation-generated accounts, sessions, uploads, and artifacts into `<batch>\validation_generated\` before the final rescan.

## Rollback

Read `moved_files_manifest.json` in reverse successful-move order. For each entry, require that the archived target exists and the original source does not exist, recreate only the parent directory, and move the target back without overwrite. Restore the backed-up `requirements.txt`, then rerun all verification commands. Sensitive content remains redacted throughout rollback reporting.

## Dry-run Command

```powershell
.\.venv\Scripts\python.exe scripts\cleanup_project_dry_run.py
```

The script only prints the plan and safety checks. It has no execution or move option.
