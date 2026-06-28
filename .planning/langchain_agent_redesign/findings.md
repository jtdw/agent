# Findings

## Phase 9 RAG readiness

- Default API vector RAG should remain opt-in after Phase 9. The new readiness helper returns `ready_for_manual_enablement`, which means an operator still has to choose when to expose or enable it.
- Provider retry/backoff is now part of `APIEmbeddingClient` diagnostics without exposing API keys. Tests inject a no-op sleep hook so retry behavior is deterministic.
- The first default GIS RAG eval fixture seeds cover soil/XGBoost workflow guidance, map preview formats, and artifact download safety. They are readiness fixtures, not a complete evaluation suite.

Date: 2026-06-27

## Phase 15 Decision eval fixtures

- The runtime planner/coordinator eval suite now covers 10 fixed GIS cases, broadening from basic inspection/table/modeling/download-safety into vector/raster processing, CRS conversion, zonal statistics, cartography, and GSCloud confirmation behavior.
- These fixtures are still offline cutover-readiness assets. They do not call the LLM, execute GIS tools, or switch active runtime behavior.
- Confirmation-sensitive cases should remain explicit in the corpus, especially artifact download and external data download requests, because they guard against over-eager coordinator continuation.

Date: 2026-06-27

## Phase 16 CI/local decision eval guard

- A fixed outputs fixture plus strict `--min-pass-rate 1.0` report is now available as a cheap cutover-readiness guard.
- The local guard script falls back from `.venv\Scripts\python.exe` to `python`, so it can run both in this Windows dev workspace and in GitHub Actions.
- The guard intentionally uses fixed expected outputs; it validates scoring, fixture completeness, and confirmation-sensitive policy wiring, but it does not yet capture real shadow planner/coordinator outputs.

Date: 2026-06-27

## Phase 17 Shadow-output capture

- Runtime planner trace output now includes a sanitized `planned_tools` list. This preserves enough information for offline decision eval without exposing prompt text, paths, or full context.
- `decision_eval capture` is a pure file conversion step from runtime decision trace/diagnostics JSON to report-ready outputs. It does not call the LLM, execute GIS tools, or switch active mode.
- The next useful step can either collect real service shadow diagnostics into files or begin a guarded active-mode cutover plan. The former gives more evidence; the latter begins migration mechanics.

Date: 2026-06-27

## Phase 18 Service diagnostics capture

- Service diagnostics capture can now be run without invoking `ask()`: it reads `GISWorkspaceService.agent_runtime_diagnostics()` and writes a JSON snapshot.
- When a `case_id` is supplied, the capture step also produces report-ready eval outputs by reusing the Phase 17 `decision_eval capture` normalization logic.
- This phase completes the offline evidence pipeline. Moving from here into active-mode behavior is a major cutover decision because it changes runtime routing risk.

Date: 2026-06-27

## Phase 19 Guarded active-mode cutover foundation

- Active mode is now protected by a second explicit environment switch. `GIS_AGENT_RUNTIME_V2=1` plus `GIS_AGENT_RUNTIME_MODE=active` is not enough; `GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER=1` is also required.
- The active planner helper is opt-in and fail-closed: if guard checks fail or runtime active planning is not `ready`, service planning falls back to the existing legacy `build_llm_task_plan()` path.
- Runtime diagnostics now expose cutover guard state, but runtime context overlay does not include this guard. This avoids changing LLM planner payload shape except when the active runtime adapter is explicitly selected.
- The next decision is operational rather than mechanical: whether to enable the guarded active mode in a target environment and collect real outcomes.

Date: 2026-06-27

## Phase 20 GLM active validation

- GLM-4.5-Air can be used for validation, but raw planner output is not stable enough to rely on alone. Observed failures include provider errors, classic/phase2 schema drift, missing `tools_read`, and `ready` plans with no actionable steps.
- Guarded active mode should treat the existing deterministic `candidate_plan` as the reliability floor. If active LLM planning fails or returns an empty non-confirmation plan, runtime should fall back to the deterministic plan rather than retrying the same LLM path.
- Confirmation-sensitive cases must remain conservative: when a plan requires confirmation or clarification, do not override it with deterministic execution in the active planner adapter.
- The decision eval corpus now matches actual registered tools better:
  - `plot_dataset` instead of logical `make_map`
  - `submit_commercial_download_job` instead of logical `submit_download_job`
  - artifact download safety uses confirmation without a nonexistent planner tool
  - `raster_zonal_stats` now has a Tool Card
- Coordinator diagnostics may return `continue` with a missing `required_tool`; this can be safely completed from `next_step_id` or the single remaining validated step without changing the decision.
- Latest fallback active eval using GLM-4.5-Air and deterministic candidate plans reached planner 0.9 and coordinator 1.0, with no GIS tool execution. The remaining planner miss is acceptable for the 0.8 cutover-eval threshold but should be investigated before broader production exposure.

Date: 2026-06-27

## Phase 21 Service-level active smoke

- A service-level active smoke runner now exercises `GISWorkspaceService.ask()` with synthetic local datasets and writes sanitized JSON under `outputs/`.
- The default smoke mode uses a lightweight runtime adapter plus deterministic coordinator. This keeps the test focused on service-level active planner routing and safe local tool execution without requiring a full LangChain `GISAgent` construction or real coordinator LLM calls.
- The real local smoke still used the current `.env` guarded active GLM-4.5-Air planner path for the active map case and succeeded with `runtime_active:default_llm`.
- Latest smoke result: 2/2 passed, no external download tools executed, and `ready_for_next_phase=true`.
- The next expansion decision is whether to broaden deterministic-coordinator safe cases first, or run a staging/local `--coordinator-mode llm` smoke that consumes more tokens and has more provider variability.

Date: 2026-06-27

## Phase 22 Active smoke expansion

- The deterministic-coordinator service smoke suite now covers three safe local paths: uploaded vector description, map generation, and table-to-points workflow-priority routing.
- Smoke pass criteria must check both expected tool execution and terminal status. A tool appearing in `executed_tools` is not enough if the presentation/execution status is `failed`, `blocked`, or `error`.
- Reusing a fixed smoke workspace can contaminate table-to-points runs through persisted workspace/session state. The runner now creates a fresh `run_id` workspace for every invocation and records that `run_id` in the report.
- Latest local smoke result: 3/3 passed with guarded active mode, lightweight runtime, deterministic coordinator, and no external download tools.
- The next meaningful risk step is coordinator LLM smoke. It should be a conscious choice because it spends GLM tokens and introduces provider variability into a service-level live-execution smoke.

Date: 2026-06-27

## Phase 23 Coordinator LLM smoke

- The first GLM-4.5-Air coordinator LLM service smoke exposed two real runtime coordination gaps that deterministic coordinator mode hid.
- Coordinator tool-card input must be hydrated from validated planned tools, not only from context retrieval. Otherwise the LLM can falsely conclude a validated tool such as `describe_dataset` is unavailable.
- If all planned steps have succeeded and the coordinator returns `continue` without a remaining `next_step_id` / `required_tool`, the executor should treat it as terminal success rather than blocking as `STEP_NOT_IN_REMAINING_PLAN`.
- Latest minimal LLM coordinator smoke result: `active_describe_vector` passed 1/1 with guarded active mode, lightweight runtime, GLM-4.5-Air coordinator, and no external download tools.
- Expansion to map generation is the next risk step. It may reveal result/artifact interpretation issues because image/artifact outputs introduce more state than the describe-only case.

Date: 2026-06-27

## Phase 24 Coordinator LLM map smoke

- `active_map_generation` passed under GLM-4.5-Air coordinator LLM mode without additional code changes.
- This validates a slightly richer service-level result path than describe-only: `plot_dataset` executed, one artifact was registered, and one image was returned.
- No external download tools were executed.
- The next decision should balance coverage and cost: adding smoke guards improves repeatability, while expanding to table-to-points under LLM coordinator spends more tokens and may expose multi-step workflow-specific issues.

Date: 2026-06-27

## Phase 25 Smoke guard integration

- CI/local active smoke guard should remain deterministic by default. LLM coordinator smoke is supported, but must require `-IncludeLlmCoordinatorSmoke` or `GIS_AGENT_RUN_LLM_COORDINATOR_SMOKE=1`.
- PowerShell wrapper scripts must check `$LASTEXITCODE` after nested native/script invocations; `$ErrorActionPreference = "Stop"` alone is not enough to fail on a child process nonzero exit code.
- GLM coordinator can return a valid `next_step_id` while leaving `required_tool` blank. This is safe to normalize from the selected validated plan step, but only when `required_tool` is empty. A non-empty mismatch remains a hard block.
- Latest Phase 25 validation: deterministic guard 3/3 passed; opt-in LLM describe 1/1 passed; opt-in LLM map 1/1 passed; no external download tools executed.
- Recommended next step is an opt-in local multi-step LLM coordinator smoke for `workflow_priority_table_to_points`, while keeping CI deterministic-only.

Date: 2026-06-27

## Phase 26 Multi-step LLM coordinator smoke

- `workflow_priority_table_to_points` passed as a single opt-in LLM coordinator smoke case, then was added to the opt-in guard suite.
- The expanded opt-in guard now covers one describe case, one map/artifact case, and one multi-step table-to-points workflow case. CI still runs only the deterministic guard.
- A new GLM drift pattern was observed after successful map execution: the terminal coordinator can emit natural-language `answer` instead of the structured decision schema. When all planned steps have already succeeded and no steps remain, treating this as `stop_success` preserves the successful tool outcome without weakening pre-execution validation.
- Latest opt-in guard result: deterministic 3/3, LLM describe 1/1, LLM map 1/1, LLM table-to-points 1/1; no external download tools executed.
- The next step is a major exposure decision, not a purely mechanical code task: keep active mode local/staging-only, or start broader user-facing active exposure with rollback and observability gates.

Date: 2026-06-27

## Phase 27 Active exposure guardrails

- Active runtime can now report a read-only exposure policy without changing live routing. The policy combines active cutover state, requested environment, requested percent, rollback flag, deterministic smoke status, optional LLM smoke status, and production override state.
- Local validation remains observe-only: `.env` uses `GIS_AGENT_RUNTIME_EXPOSURE_ENV=local` and `GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=0`, so diagnostics reports `eligible_for_user_exposure=false` even when active mode and deterministic smoke pass.
- Smoke report paths are exposed only as filenames in diagnostics. This avoids leaking local absolute workspace paths through admin diagnostics.
- Staging exposure is intentionally capped by policy at an initial 10% ceiling. Production exposure requires an explicit extra override.
- The decision eval guard script now checks child exit codes with `Invoke-Checked`, avoiding a false green if pytest fails before the fixed report command succeeds.
- Next choice: keep this as diagnostics-only, or add an admin read-only exposure endpoint/runbook plus a staging 1-10% rollout procedure.

Date: 2026-06-28

## Phase 28 Staging exposure runbook/API

- Admins now have a dedicated read-only endpoint: `/api/admin/agent-runtime/exposure`. It uses the same admin token protection and sanitizer as runtime diagnostics.
- The endpoint does not execute smoke tests, call LLMs, rebuild indexes, or change traffic. It only evaluates current env/config/report files.
- The existing sanitizer was too broad for this endpoint because it removed any key containing `env`; `environment` is now explicitly allowed while sensitive env/path/token/cookie fields still remain filtered.
- The staging runbook documents the intended first rollout ladder: observe-only, 1%, 5%, then 10%, with `GIS_AGENT_RUNTIME_ROLLBACK=1` as the primary rollback.
- Production exposure remains blocked unless a separate production override is enabled.
- Next choice: perform a staging dry-run and capture endpoint evidence, or expand smoke coverage before any dry-run.

Date: 2026-06-28

## Phase 29-32 Dry-run, Smoke, Script, Report Enhancements

- Staging exposure can now be rehearsed without traffic changes via `scripts/run_agent_runtime_staging_exposure_dry_run.ps1`.
- The dry-run evidence file is `outputs/agent_runtime_exposure_staging_dry_run.json`; latest run reported staging 1%, deterministic smoke 5/5, `eligible_for_user_exposure=true`, and `live_traffic_changed=false`.
- Default deterministic active smoke now covers five stable local cases:
  - uploaded vector description
  - uploaded table description
  - vector map generation
  - secondary vector map generation
  - table-to-points workflow
- Raster clip/basic-stat and table-to-points-map candidates exposed active planner instability during expansion. They should not be used as default active smoke gates until planner routing is hardened; keep relying on offline decision eval and direct tool tests for those paths for now.
- Exposure reports now include `checked_at`, `required_reports`, `blocking_reasons_human`, and `next_actions`, which makes the admin endpoint closer to a real rollout gate.
- Next major choice is whether to introduce a controlled staging 1% routing mechanism, or broaden active smoke/eval further before any real traffic routing.

Date: 2026-06-28

## Phase 33 Active planner GIS stability hardening

- ArcGIS/ArcPy docs were used as a semantic GIS taxonomy reference only: raster clip, vector clip, raster statistics, and cartographic export remain implemented through the existing project tools rather than adding an ArcPy runtime dependency.
- Active planner instability for raster/clip/cartography had two root causes:
  - runtime deterministic fallback only recognized `workflow_plan`, `tool_plan`, or `validated_tool_args`; ready registered `executable_workflow` plans were not promoted into executable fallback plans.
  - raster clip prompts containing DEM/raster language could be misclassified or matched through the generic vector clip template before reaching `clip_raster_by_vector`.
- The deterministic planner now treats local uploaded/active dataset clip/map requests as local processing/cartography instead of download when a dataset is already present.
- Default deterministic active smoke now covers nine local cases:
  - uploaded vector description
  - uploaded table description
  - vector map generation
  - secondary vector map generation
  - table-to-points workflow
  - raster basic statistics
  - raster clip by vector boundary
  - vector clip followed by map generation
  - table-to-points followed by map generation
- Latest staging dry-run evidence reports deterministic smoke 9/9, `eligible_for_user_exposure=true`, and `live_traffic_changed=false`.
- Real 1% traffic remains a separate Phase 34 choice; this phase did not change live routing percent or enable production exposure.

Date: 2026-06-28

## Phase 34 Pre-1% LLM coordinator evidence

- Real staging 1% traffic remains disabled. This phase broadened opt-in LLM coordinator evidence instead of changing routing percent.
- GLM coordinator can return `continue` with a valid `required_tool` but blank `next_step_id`. This is safe to normalize only when exactly one remaining planned step uses that tool; non-empty mismatches and ambiguous matches remain blocked.
- GLM planner can emit `tool_plan` without explicit `step_id` while using `$steps.<execution_step>.outputs...` references. Coordinated execution now normalizes safe identifier-like `execution_steps` into step ids for that execution, so downstream `$steps.make_points...` references resolve consistently.
- Latest full opt-in LLM guard passed: deterministic smoke 9/9 plus six LLM coordinator cases (`active_describe_vector`, `active_map_generation`, `workflow_priority_table_to_points`, `active_raster_clip_by_boundary`, `active_vector_clip_map`, `active_table_to_points_map`) all 1/1.
- This improves pre-1% confidence for raster clip, vector clip cartography, and table-to-points cartography, but it is still local/staging evidence and not a substitute for controlled real-traffic rollout metrics.

Date: 2026-06-28

## Phase 35 Controlled staging traffic router

- Real staging 1% traffic is still not enabled in local `.env`; `GIS_AGENT_RUNTIME_EXPOSURE_ENV=local`, `GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=0`, and `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=0` remain the default local posture.
- A new traffic router boundary makes exposure enforcement explicit. Active cutover can still be used for local/smoke validation, but real percentage routing only applies when `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1`.
- When enforced, the router requires the existing exposure policy to be eligible, then uses a stable SHA-256 bucket over salt + user + session + request text. Requests outside the bucket fall back to the legacy planner instead of active runtime.
- The router returns a short `bucket_key` hash for diagnostics and does not expose raw user/session/request text.
- This phase prepares controlled staging 1% without changing live traffic. The next major choice is whether to actually set staging env values and observe real request metrics.

Date: 2026-06-28

## Phase 36 Staging 1% enablement

- User confirmed the major choice to enable staging 1%.
- Local `.env` now has `GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging`, `GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=1`, and `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1`.
- `GIS_AGENT_RUNTIME_ROLLBACK=0` and `GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=0`; production exposure remains blocked.
- A fresh exposure check loaded `.env` and reported active guard effective, deterministic smoke passed 9/9, six LLM coordinator smoke reports passed, `eligible_for_user_exposure=true`, and `recommendation=allow_staging_exposure`.
- Uvicorn on `127.0.0.1:8765` was restarted so the running API process reads the new `.env`. The admin endpoint `/api/admin/agent-runtime/exposure` confirmed staging 1% eligibility.
- Phase 37 should observe real request routing/outcomes and perform a rollback toggle drill before increasing to 5%.

Date: 2026-06-28

## Phase 37 Staging 1% observation and rollback drill

- Staging 1% routing evidence was collected without changing production exposure. The observation summary recorded 200 deterministic routing samples, with 3 active hits and 197 legacy fallback decisions under enforced routing.
- Direct unauthenticated HTTP chat observation returned 403. This is the correct safety posture for the current API; authentication was not weakened merely to collect observation traffic.
- A follow-up authenticated real HTTP chat observation succeeded end-to-end: temporary user registration, cookie-backed `/api/auth/me`, chat session creation, `tool_enabled` mode, and `/api/chat/ask` all returned 200.
- The authenticated request was a safe answer-only workspace capability prompt. Its computed exposure routing bucket was 74, so under staging 1% it correctly remained outside the active bucket and used legacy fallback (`outside_exposure_bucket`).
- An authenticated active-bucket search produced a bucket 0 request for a safe missing-dataset inspection prompt. The request completed with HTTP 200, but because no dataset was present the active planner did not produce a ready executable plan and the service safely returned answer-only fallback. This is acceptable, but it is not enough evidence for increasing exposure.
- A stronger authenticated active-hit observation used the real HTTP upload path: temporary authenticated user, bucket 0 chat session, `tool_enabled`, CSV upload, then `check this dataset`. The request completed as `coordinated_workflow` with `presentation_status=succeeded`.
- The successful active-hit uploaded-dataset observation exposed runtime metadata in assistant meta: `planner_source=runtime_active:deterministic_fallback` and `runtime_exposure_routing.reason=selected_for_active_runtime`, bucket 0.
- Rollback drill passed: setting `GIS_AGENT_RUNTIME_ROLLBACK=1` made the admin exposure report return `eligible_for_user_exposure=false`, `recommendation=do_not_expose_users`, and `reasons=["rollback_requested"]`.
- Rollback was restored to `0`; the restored exposure report returned `eligible_for_user_exposure=true` and `recommendation=allow_staging_exposure`.
- Current local config remains staging 1%, enforced routing on, rollback off, and production override off. The active-hit dataset success makes Phase 38 more defensible, but increasing to 5% remains a major rollout decision and should not be automated without user confirmation.

Date: 2026-06-28

## ISMN, XGBoost, and GeoConformal Prediction Design Findings

- The requested `tGCP` direction refers to the paper's GeoConformal Prediction / GCP concept, not a separate project-specific tool name.
- The first implementation should respect ISMN authorization boundaries: only read user-uploaded official archives, existing workspace archives, and archives already placed under the agent's local library. It should not automate ISMN account login or store credentials/cookies/storage state.
- `TUW-GEO/ismn` should be treated as an optional local archive reader. Missing dependency should return `ISMN_DEPENDENCY_MISSING` rather than breaking backend startup.
- The agent needs data semantic cards so it can distinguish observation targets, model features, calibration sets, prediction tables, map-ready layers, and derived artifacts without guessing from filenames.
- The first GCP scope should focus on model-agnostic regression intervals using absolute residual nonconformity, global split conformal as safe baseline, and spatially adaptive weighting only when coordinates/calibration data are sufficient.

Date: 2026-06-28

## Phase 38 Staging 5% Attempt Findings

- The local `.env` contained several runtime rollout keys embedded in corrupted comment lines, so strict line-based parsing only saw `GIS_AGENT_RUNTIME_EXPOSURE_PERCENT`. Adding standalone runtime override lines made the API process correctly read active guard, smoke report, rollback, and production-exposure settings.
- After enabling staging 5% and restarting uvicorn, `/api/admin/agent-runtime/exposure` reported `requested_percent=5`, `eligible_for_user_exposure=true`, `recommendation=allow_staging_exposure`, `rollback_requested=false`, and no blocking reasons.
- A fresh Phase 38 deterministic active smoke rerun did not pass: 9 cases, 2 passed, 7 failed, `ready_for_next_phase=false`.
- The failed smoke cases did not execute external download tools. Failures were planner/plan-validity failures: `default_llm` produced invalid responses, invalid plans, clarification, or missing-input plans for several established smoke cases.
- Because the fresh smoke failed, staging 5% should not be held. The local runtime was returned to staging 1% and the admin exposure endpoint again reported eligible at 1%.
- Before retrying 5%, investigate active planner drift and decide whether to tighten deterministic fallback, isolate smoke from default LLM drift, or add a stronger planner validity gate. Do not start ISMN/XGBoost/GCP implementation until the 5% runtime rollout is stable.

Date: 2026-06-28

## Phase 38A Active Planner Drift Remediation Findings

- Root cause was narrower than first suspected: fresh active smoke inherited `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1` from `.env`, so most smoke cases were bucketed outside 1%/5% and routed back to legacy/default LLM planning. The smoke runner was not actually validating active runtime for those cases.
- `run_service_active_smoke()` now temporarily disables percentage exposure routing while it runs, so active smoke validates active runtime directly and is not affected by the current staging percentage.
- Active fallback was also tightened for executable deterministic plans: if the LLM planner returns a ready plan that asks for clarification or lacks executable actions while the deterministic plan already has validated actions, the runtime uses deterministic fallback. If the deterministic plan itself needs user input and has no actions, LLM clarification is preserved.
- Phase 38A fresh smoke passed 9/9, and a Phase 38A staging 5% dry-run reported eligible with `live_traffic_changed=false`.
- After updating `.env` to staging 5% and restarting uvicorn, `/api/admin/agent-runtime/exposure` reported `requested_percent=5`, eligible, rollback false, and no blocking reasons.
- A real authenticated bucket-1 request with CSV upload succeeded as `coordinated_workflow` with `presentation_status=succeeded`, giving active-hit evidence at 5%.

Date: 2026-06-28

## Phase 39 Implementation Plan Findings

- Phase 39 should begin with a data semantic card foundation before ISMN import, XGBoost metadata, or GCP upgrades. Without this layer the planner would continue guessing scientific roles from filenames and prompt wording.
- Existing `core/workflows/stm_soil_moisture.py`, `core/ml/generic_xgboost.py`, and `core/gcp_uncertainty.py` already provide useful foundations. The implementation plan keeps them compatible and extends outputs/contracts instead of replacing them.
- `core/station_data.py` contains older `.stm` archive parsing and visible historical mojibake. Phase 39 should not combine the ISMN/GCP upgrade with broad encoding repair; only mark blocking cases for later review.
- ISMN archive access remains local-only: uploaded official archives, workspace archives, or `local_library/data/ismn/**/*.zip`. `TUW-GEO/ismn` should stay optional at first, with `ISMN_DEPENDENCY_MISSING` as a structured error.
- The recommended first code batch is Phase 39.1 plus 39.2: semantic cards and local ISMN adapter/tools. This lowers downstream planner and modeling risk.
- User later confirmed that the old `core/station_data.py` `.stm` parser should be migrated away and deleted after replacement. Direct deletion now would break `core/tools/common_tools.py`, `core/workflows/stm_soil_moisture.py`, `api_server.py`, and STM tests, so deletion is a Phase 39.3 migration completion criterion rather than a Phase 39.1 action.
- GitNexus impact for Phase 39.1 showed `build_conversation_context` as HIGH risk, `format_context_for_agent` as LOW risk, `put_table` as MEDIUM, `put_raster_path` as HIGH, and `put_vector` as CRITICAL. Therefore Phase 39.1 should avoid editing `DataManager.put_*` and attach semantic cards through separate helpers.
- Phase 39.3 completed the old parser migration. Runtime imports no longer reference `core.station_data`; the compatibility tool name `convert_stm_station_archive_to_training_table` remains, but it now calls `core.ismn_adapter.ismn_archive_to_observation_dataframe`.
- `core/station_data.py` was deleted after `rg "core.station_data|from core.station_data|station_data|stm_archive_to_training_dataframe|find_station_archives|parse_ismn_station_zip" core api_server.py tests` returned no runtime/test matches.
- `build_common_tools` impact was CRITICAL because tool registration feeds workflow executor, active smoke, and service ask paths. The implementation kept tool names compatible and changed only the internal parser dependency.
- Adding ISMN tool cards increased formatted prompt size beyond the existing 20000-character budget. The fix was to compact tool-card list fields and serialize only the top 5 candidate cards in `format_context_for_agent`, while leaving `candidate_tool_cards()` retrieval limits unchanged.
- Phase 39.4 impact analysis showed `run_generic_xgboost_workflow`, `_fit_table_model`, and `_split_indices` as LOW risk individually. The full-worktree `detect-changes` reported HIGH because many earlier Phase 38/39 files remain dirty in the same checkout.
- Generic XGBoost now emits a stable GCP-ready contract: `xgb_prediction`, `xgb_residual`, `xgb_validation_prediction`, `xgb_validation_residual`, `xgb_validation_fold`, `xgb_validation_role`, plus outputs/diagnostics for target, prediction, residual, validation method, coordinate columns, time column, and feature semantics.
- Random validation fallback is explicitly reported through `limitations=["random_split_validation"]`, making it easier for later GCP routing to distinguish spatial/temporal evidence from weak random holdout evidence.
- Phase 39.5 impact analysis showed `run_gcp_uncertainty_analysis` and the registered `geographical_conformal_prediction` wrapper as LOW risk.
- GCP method names are now explicit: `global_split_conformal`, `spatially_weighted_gcp`, and `global_split_conformal_fallback`.
- Spatial fallback is now structured with codes such as `GCP_COORDINATES_MISSING_GLOBAL_FALLBACK` and `GCP_COORDINATES_INSUFFICIENT_GLOBAL_FALLBACK`, and the fallback diagnostics are copied into metrics, summary JSON, tool outputs, diagnostics, and result semantic cards.
- GCP prediction tables now include `gcp_local_quantile`, `gcp_method`, `gcp_fallback_code`, and `gcp_interval_score`, plus per-prediction alias columns such as `<pred>_gcp_local_quantile` and `<pred>_gcp_method`.
- The registered `geographical_conformal_prediction` tool attaches a sanitized data semantic card to the result dataset with roles `prediction_with_uncertainty`, `gcp_result`, `map_ready`, and `calibration_diagnostics`.
- `core/tools/ml_tools.py` still contains an unreachable legacy GCP implementation block after the registered wrapper return path. It is not executed by `build_ml_tools()` but still contains old method literals; defer cleanup to a separate targeted refactor rather than mixing it into Phase 39.5.
- Phase 39.6 impact analysis showed `build_task_plan`, `_seed_modeling_fields_from_profile`, `_recent_model_for_gcp`, and `_build_gcp_args_from_recent_model` as HIGH risk because they feed `GISWorkspaceService.ask` and the edit/retry flow. The implementation stayed narrow in `core/task_planner.py` and added dedicated planner tests.
- Phase 39.6 planner routing now reads sanitized `data_semantic_cards` to seed ISMN observation modeling fields, preserve "no features means clarify" behavior, route XGBoost prediction cards to `geographical_conformal_prediction`, and treat GCP result cards as result/map-ready context rather than retraining input.
- Phase 39.7 found an active-runtime drift case: prompts like "plot the GCP uncertainty map" can be classified as `modeling` because of GCP keywords, and the active LLM planner may skip the required `table_to_points` prerequisite by calling `plot_dataset` directly on a table. The fix is two-layered: deterministic planner now overrides GCP-result map prompts to `map_generation`, and the active runtime fallback detects when an LLM plan skips `table_to_points` while deterministic planning has the safe table-to-points map workflow.

Date: 2026-06-28

## Project Findings

- The project is a GIS intelligent workbench, not a generic chatbot.
- Existing architecture already includes:
  - `core/agent.py` with LangChain-style agent entry behavior.
  - `core/tools/registry.py` for GIS tool registration.
  - `core/llm_task_planner.py` for LLM planning and fallback behavior.
  - `core/workflow_executor.py` for deterministic workflow execution.
  - `core/workflow_coordinator.py` for coordinator decisions.
  - `core/context_builder.py` and `core/capability_config.py` for context and knowledge/tool card assembly.
- Current standard LCEL is not complete.
- Current RAG is closer to keyword/rule-enhanced retrieval than complete embedding/vector-store RAG.

## LangChain Findings

- The LangChain overview positions `create_agent` as the high-level agent entry point with model, tools, and system prompt.
- LangChain's production agent stack emphasizes standard components such as models, prompts, tools, middleware, retrieval, short-term memory, streaming, structured output, and observability.
- Durable and complex agent workflows are aligned with LangGraph concepts: persistence, human-in-the-loop, and long-running execution.
- RAG should be treated as a pipeline: documents/loaders, splitting, embeddings, vector store, retriever, contextual answer generation, and evaluation.

## GIS Findings

- GIS tasks should remain deterministic where possible: validate input files, CRS, bounds, workspace permissions, user/session binding, and artifact registration.
- ArcGIS Pro help can be used as a GIS operation taxonomy reference, but the first implementation should not hard-code ArcGIS-specific behavior.

## Phase 4 Findings

- `build_llm_task_plan()` and `build_shadow_llm_task_plan()` are MEDIUM impact symbols; `build_coordinator_decision()` is HIGH impact. Phase 4 should call them from an adapter rather than edit them directly.
- `build_shadow_llm_task_plan()` already guarantees `executes_tools=False`, making it suitable for runtime shadow diagnostics.
- `build_coordinator_decision()` returns a decision and payload but does not execute tools by itself; this makes it suitable for coordinator diagnostics when invoked with an injected client.
- `llm_task_planner._call_client()` whitelists context keys. A runtime adapter cannot rely on top-level `runtime` reaching the LLM planner payload, so the adapter mirrors runtime metadata into the already-whitelisted `agent_policy` field.

## Phase 5 Findings

- `langchain_core` is installed and exposes runnable/vectorstore abstractions, but `faiss`, `chromadb`, and `langchain_community` are not installed in the project environment.
- `sklearn` and `numpy` are installed, so a local in-memory TF-IDF vector scaffold can be implemented and tested without new dependencies.
- The local TF-IDF scaffold is vectorized retrieval, but it is not equivalent to a production embedding/vector-store RAG stack. It should remain labelled as partial until a real embedding provider, persisted vector store, document loader/splitter, retriever, and evaluation path are added.

## Phase 6 Findings

- `build_conversation_context()` is MEDIUM impact with one affected flow (`Edit_user_message_and_retry`), so vector RAG context integration should remain opt-in until broader regression coverage is run.
- The default context path still uses existing keyword/rule retrieval via `knowledge_snippets`, `candidate_tool_cards`, `download_candidates`, and `area_candidates`.
- `GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT=1` now adds `vector_knowledge_snippets` and `rag_trace`; without that flag, those fields are absent and existing prompt/context behavior stays unchanged.
- The opt-in context integration still reports `full_vector_rag=False`; it is a scaffold for later production RAG, not the final embedding/vector-store pipeline.

## Phase 7 Findings

- User selected option 2: API embedding provider plus local persistent vector store.
- The project already has `openai`, `requests`, `httpx`, `numpy`, and `sklearn` dependencies, so an OpenAI-compatible embedding HTTP client can be implemented without adding requirements.
- The API embedding backend is configured through environment variables:
  - `GIS_AGENT_VECTOR_RAG_BACKEND=api`
  - `GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT=1`
  - `GIS_AGENT_EMBEDDING_API_KEY`
  - `GIS_AGENT_EMBEDDING_BASE_URL`
  - `GIS_AGENT_EMBEDDING_MODEL`
  - `GIS_AGENT_VECTOR_RAG_STORE`
- API keys are not exposed in diagnostics; diagnostics only report whether a key/base URL is configured.
- The current persistent store is local JSON, suitable for initial integration and tests. It is not yet optimized for large corpora or concurrent rebuilds.

## Phase 8 Findings

- Persistent RAG needs freshness checks before any default enablement; otherwise stale JSON vectors can silently lag behind updated knowledge documents.
- A source-hash manifest is sufficient for the first local JSON backend: it detects document count changes and content/metadata hash changes.
- Provider failure observability should return structured errors and redact API keys or known secret values from error messages.
- A small recall@k evaluator is now available for regression fixtures, but production readiness still needs a larger GIS-specific evaluation set before default enablement.

## Phase 45/46 Real Smoke and Recurring Guard Findings

- The real Shandianhe soil moisture/GCP three-sample smoke completed successfully even though the original shell invocation hit the outer timeout. The generated evidence showed all three dates completed full STM/XGBoost/raster-prediction/GCP outputs.
- Full three-case recomputation took about 31 minutes. This is appropriate for strong regression evidence but should not be the default recurring guard.
- A recurring guard can validate the full-smoke evidence quickly by checking case count, per-case workflow status, mapped prediction output, nonzero valid pixels, GCP report presence, empirical coverage threshold, and study-area boundary filtering.
- This keeps later staging decisions grounded in real outputs while avoiding repeated DEM derivative, temporal composite, raster prediction, and GCP recomputation on every local guard run.

Date: 2026-06-29
