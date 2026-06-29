# LangChain GIS Agent Redesign Plan

Status: in_progress
Date: 2026-06-27

## Goal

Generate a Chinese implementation plan for redesigning the GIS agent around the LangChain overview and the user's selected "方案 1", without generating code.

## Scope

- Review current GIS agent architecture at the planning level.
- Align the redesign with LangChain concepts: agent harness, tools, middleware, context, retrieval, LCEL, workflow durability, observability.
- Explicitly mark current standard LCEL and vectorized RAG as incomplete and convert them into planned work.
- Preserve existing API/frontend behavior during future implementation.

## Phases

| Phase | Status | Notes |
| --- | --- | --- |
| Context and source review | complete | Used existing project context and official LangChain docs supplied by the user. |
| Plan structure | complete | Chose phased migration with a new runtime boundary instead of direct replacement. |
| Formal plan document | complete | Wrote `docs/superpowers/plans/2026-06-27-langchain-gis-agent-redesign-plan.md`. |
| Verification | complete | No code generated; only markdown planning files changed. |

## Decisions

- Use a hybrid architecture: LangChain agent harness + deterministic GIS workflow executor.
- Do not remove `core/agent.py`, `core/llm_task_planner.py`, or `core/workflow_executor.py` in the first implementation batch.
- Build `core/agent_runtime/` as a new boundary and migrate traffic gradually.
- Treat standard LCEL and vector RAG as explicit construction phases, not existing complete capabilities.

## Errors Encountered

None.

## Implementation Checkpoints

| Checkpoint | Status | Notes |
| --- | --- | --- |
| Phase 0 baseline | complete | Ran lightweight API/helper and workflow smoke baseline: 13 tests passed before implementation. |
| Phase 1 runtime shell | complete | Added `core/agent_runtime/` and attached a disabled-by-default runtime wrapper to `GISAgent`. |
| Phase 1 cutover | pending | No execution cutover yet; `GISAgent.ask()` still uses the existing legacy agent path. |
| Phase 2 runtime context | complete | Added `AgentRuntimeContext` with manager scope, ToolRuntimeContext bridge, and workspace path guard. |
| Phase 3 tool runtime standardization | complete | Added read-only `RuntimeToolSpec` adapter, runtime prechecks, context overlay, and in-memory shadow trace; did not modify `build_tools` or live tool execution. |
| Phase 4 planner/coordinator runtime adapter | complete | Added a side-channel `RuntimePlannerAdapter` for shadow task-plan diagnostics and coordinator decision diagnostics. `service.ask()` now uses the adapter only when runtime v2 is explicitly enabled; default behavior still delegates to the legacy shadow planner path. It does not modify `build_llm_task_plan()`, `build_shadow_llm_task_plan()`, `build_coordinator_decision()`, or tool execution. |
| Phase 5 LCEL chain boundary | complete | Added partial LCEL-style runtime chain wrappers for answer-only context, retrieval context, and result-summary context. Added a local TF-IDF vector RAG scaffold. This is not a full LCEL migration and not a full embedding/vector-store RAG implementation. |
| Phase 6 Context/RAG integration | complete | Added opt-in context integration behind `GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT=1`. Default keyword retrieval and tool-card behavior are unchanged. |
| Phase 7 Production RAG backend | complete | User selected option 2. Added OpenAI-compatible API embedding client and local JSON persistent vector store, with opt-in context use via `GIS_AGENT_VECTOR_RAG_BACKEND=api`. |
| Phase 8 RAG evaluation and ingestion hardening | complete | Added persistent index ingestion wrapper, source-hash freshness checks, provider failure observability, and recall@k evaluation. Still opt-in; default enablement should wait for broader eval and operational limits. |
| Phase 9 Default enablement readiness | complete | Added readiness policy, default GIS eval fixture seeds, and embedding provider retry/backoff. It still only reports `ready_for_manual_enablement`; vector RAG is not default-enabled. |
| Phase 10 RAG operations controls | complete | User selected option 1. Added admin-only read-only RAG readiness/eval status API. It does not rebuild indexes, call embedding providers, or expose ordinary workspace UI. |
| Phase 11 RAG operations execution | complete | Added CLI-only RAG operations via `python -m core.agent_runtime.rag_ops`: read-only status, confirmed rebuild, and eval/readiness against an existing persistent index. No admin write API added. |
| Phase 12 Runtime migration continuation | complete | Added runtime-facing planner/coordinator input/output schemas and unified runtime decision trace diagnostics. Live execution remains legacy by default. |
| Phase 13 Runtime cutover readiness | complete | Added fixed GIS planner/coordinator decision eval fixtures and pure scoring helpers. Did not modify live planner/coordinator execution. |
| Phase 14 Guarded cutover preparation | complete | Added `python -m core.agent_runtime.decision_eval` with `fixtures` and `report --outputs` commands for offline planner/coordinator eval reporting. |
| Phase 15 Active-mode cutover planning | complete | User selected fixture expansion. Expanded offline planner/coordinator eval coverage to 10 core GIS workflow and safety cases; no live execution cutover. |
| Phase 16 Decision eval CI/local wiring | complete | User selected CI/local guard. Added fixed outputs fixture, local PowerShell regression script, pytest coverage, and CI job step with strict 1.0 pass-rate report. |
| Phase 17 Shadow-output capture for eval reports | complete | Added report-ready capture from runtime decision trace/diagnostics JSON, including safe planner tool names in trace output. No LLM calls, no tool calls, no active-mode cutover. |
| Phase 18 Service shadow diagnostics capture | complete | Added service diagnostics capture CLI/helper and script. It writes runtime diagnostics JSON and optional report-ready eval outputs from `GISWorkspaceService.agent_runtime_diagnostics()` without chat execution, LLM calls, tool calls, or active-mode cutover. |
| Phase 19 Guarded active-mode cutover foundation | complete | Added explicit active cutover guard, diagnostics visibility, runtime adapter active planner helper, service active planner helper, legacy fallback, and CI guard coverage. Default behavior remains legacy unless `GIS_AGENT_RUNTIME_V2=1`, `GIS_AGENT_RUNTIME_MODE=active`, and `GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER=1` are all set. |
| Phase 20 Active enablement and GLM validation | complete | User enabled guarded active mode locally and requested GLM-4.5-Air-only validation. Added eval/schema alignment, `raster_zonal_stats` Tool Card, active deterministic fallback, and coordinator required-tool normalization. Latest fallback active eval: planner 0.9, coordinator 1.0, `ready_for_cutover_eval=true`; no tools executed. |
| Phase 21 Service-level active smoke decision | complete | Added and ran a guarded service-level active smoke runner with synthetic in-workspace datasets. Latest smoke: 2/2 passed, `ready_for_next_phase=true`, no external download tools executed. |
| Phase 22 Active smoke expansion decision | complete | Chose the safer path first: broadened deterministic-coordinator service smoke from 2 to 3 cases by adding uploaded-vector description. Tightened smoke pass criteria and isolated each run in a fresh workspace. Latest smoke: 3/3 passed, `ready_for_next_phase=true`, no external download tools executed. |
| Phase 23 Coordinator LLM smoke decision | complete | Ran the minimal GLM-4.5-Air `--coordinator-mode llm` service smoke for `active_describe_vector`. Initial failure exposed coordinator input/terminal-decision issues; fixed planned-tool-card hydration and normalized empty `continue` after successful final step to `stop_success`. Latest LLM coordinator smoke: 1/1 passed, no external download tools executed. |
| Phase 24 Coordinator LLM smoke expansion decision | complete | Expanded LLM coordinator smoke to `active_map_generation`. It passed 1/1 with artifact/image output, no code changes needed, no external download tools executed. |
| Phase 25 Smoke guard integration | complete | Added local/CI deterministic active smoke guard with LLM coordinator smoke kept explicit opt-in. Fixed guard exit-code propagation and coordinator blank `required_tool` handling. Latest deterministic guard: 3/3 passed. Latest opt-in LLM guard: describe 1/1, map 1/1. |
| Phase 26 Multi-step LLM coordinator smoke | complete | Ran and added opt-in local LLM coordinator smoke for `workflow_priority_table_to_points`. Latest opt-in LLM guard covers describe, map, and table-to-points; all passed 1/1. CI remains deterministic-only. |
| Phase 27 Active exposure guardrails | complete | Added read-only active exposure policy diagnostics with environment, percent, rollback, deterministic smoke, optional LLM smoke, and production override gates. Local `.env` remains observe-only with 0% exposure. |
| Phase 28 Staging exposure runbook/API | complete | Added admin-only read-only `/api/admin/agent-runtime/exposure`, sanitized exposure report wiring, and Chinese staging 1%-10% rollout/runback runbook. No live traffic routing changed. |
| Phase 29 Staging dry-run execution | complete | Ran local staging 1% dry-run evidence generation. Output `outputs/agent_runtime_exposure_staging_dry_run.json` reports deterministic smoke 5/5, `eligible_for_user_exposure=true`, and `live_traffic_changed=false`. |
| Phase 30 Active smoke expansion | complete | Expanded deterministic active smoke default suite from 3 to 5 stable local cases: vector describe, table describe, vector map, secondary vector map, and table-to-points. Deferred unstable raster/vector processing active smoke candidates to offline eval/tool tests. |
| Phase 31 Staging dry-run script | complete | Added `scripts/run_agent_runtime_staging_exposure_dry_run.ps1`, which runs deterministic active smoke and writes staging exposure evidence with checked child exit codes. |
| Phase 32 Exposure report enhancement | complete | Added `checked_at`, `required_reports`, `blocking_reasons_human`, and `next_actions` to exposure reports and admin endpoint responses. |
| Phase 33 Active planner GIS stability hardening | complete | Hardened deterministic active fallback and default smoke for raster stats, raster clip, vector clip + map, and table-to-points + map. Latest deterministic smoke: 9/9; staging dry-run evidence updated with no live traffic change. |
| Phase 34 Pre-1% LLM coordinator evidence | complete | Kept real staging 1% disabled. Added opt-in LLM coordinator smoke coverage for raster clip, vector clip + map, and table-to-points + map; latest full opt-in guard passed deterministic 9/9 plus six LLM coordinator cases. |
| Phase 35 Controlled staging traffic router | complete | Added disabled-by-default exposure routing enforcement. When `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1`, eligible staging requests are bucketed by stable hash and non-selected requests fall back to legacy. Local `.env` still keeps routing enforcement off and exposure percent at 0. |
| Phase 36 Staging 1% enablement | complete | User confirmed the major choice. Local `.env` now sets staging 1% and enforced exposure routing. Uvicorn on 127.0.0.1:8765 was restarted and admin exposure endpoint reports `eligible_for_user_exposure=true`, `recommendation=allow_staging_exposure`. Production exposure remains disabled. |
| Phase 37 Staging 1% observation and rollback drill | complete | Collected staging 1% routing evidence, confirmed auth blocks unauthenticated chat observation without weakening access control, passed rollback toggle drill, added authenticated real HTTP fallback observation, and captured an authenticated active-hit uploaded-dataset success. Evidence: `outputs/agent_runtime_phase37_staging_1pct_observation.json`, `outputs/agent_runtime_phase37_authenticated_chat_observation.json`, `outputs/agent_runtime_phase37_authenticated_active_hit_dataset_observation.json`. |
| GIS tool upgrade design: ISMN + XGBoost + GCP | complete | User confirmed the design direction for local ISMN archive ingestion, soil-moisture XGBoost updates, and GeoConformal Prediction outputs. Wrote `docs/superpowers/specs/2026-06-28-ismn-soil-moisture-xgboost-gcp-design.md`. No implementation code changed. |
| Phase 38 Staging 5% exposure attempt | complete | User confirmed execution. The first 5% attempt was returned to 1% after fresh smoke failed due percentage routing contaminating active-smoke validation. Evidence: `outputs/agent_runtime_phase38_staging_5pct_attempt_summary.json`. |
| Phase 38A Active planner drift remediation | complete | Fixed active-smoke isolation from percentage routing and tightened active fallback for LLM clarification drift when deterministic plans are executable. Fresh smoke passed 9/9, 5% dry-run was eligible, admin exposure reports staging 5%, and an authenticated bucket-1 uploaded-dataset request succeeded. Evidence: `outputs/agent_runtime_phase38a_staging_5pct_dry_run_fixed.json`, `outputs/agent_runtime_phase38a_authenticated_active_hit_5pct_fixed.json`. |
| Phase 39 Soil Moisture + XGBoost + GCP implementation plan | complete | Wrote `docs/superpowers/plans/2026-06-28-soil-moisture-xgboost-gcp-implementation-plan.md`. No implementation code changed. |
| Phase 39.1 Data semantic card foundation | complete | Added `core/data_semantics.py`, sanitized planner context integration, and tests. Avoided DataManager put_* edits due HIGH/CRITICAL impact. |
| Phase 39.2 ISMN local archive adapter and tools | complete | Added local-only ISMN archive discovery/profile/import tools, tool cards, and registry wiring. `ismn` remains optional and missing dependency is structured. |
| Phase 39.3 Soil moisture workflow migration off station_data.py | complete | Moved local STM-compatible ISMN archive parsing into `core/ismn_adapter.py`, rewired tools/workflow/API, migrated tests, and deleted `core/station_data.py`. |
| Phase 39.4 XGBoost output contract and validation metadata | complete | Added GCP-ready prediction/residual/validation columns, method metadata, feature semantics, validation method, coordinate/time outputs, and random split limitation reporting. |
| Phase 39.5 GCP output, fallback, and semantic-card upgrade | complete | Added explicit GCP method names, structured fallback diagnostics, local quantile/row interval-score columns, result semantic cards, and fallback-aware tool outputs. |
| Phase 39.6 Planner/context/runtime semantic routing | complete | Added semantic-card planner routing for ISMN observation modeling, XGBoost prediction-to-GCP, GCP result analysis, and GCP uncertainty map fields. |
| Phase 39.7 Verification, smoke, and rollout decision | complete | Added opt-in semantic GCP-result map active smoke, fixed modeling-to-map semantic intent override and table-to-points fallback drift, ran deterministic 9/9 smoke, opt-in semantic 1/1 smoke, and staging 5% dry-run evidence. |
| Phase 45 Real soil moisture/GCP three-sample smoke | complete | Recovered and verified three real Shandianhe samples for 2019-07-15, 2019-05-15, and 2019-01-15. All completed STM/XGBoost raster prediction/GCP with study-area boundary filtering. |
| Phase 46 Lightweight recurring smoke gate | complete | Added a no-recompute recurring evidence runner for Phase 45 outputs: `core/workflows/soil_moisture_gcp_smoke.py`, `scripts/run_soil_moisture_gcp_smoke.ps1`, and tests. |
| Phase 47 Staging 10% readiness dry-run gate | complete | Added and pushed the staging 10% readiness dry-run gate. Commit `4238d75`; later runbook hardening commit `eb3cc64`. |
| Phase 48 Staging 10% observation start | complete | Local backend was observed on `127.0.0.1:8765`; admin exposure reported staging 10%, eligible, soil gate passed, active smoke 9/9, routing sample about 9.8%. Evidence: `outputs/phase48_staging10_observation_start.json`. |
| Phase 49 Staging 10% observation window | complete | First observation window completed with policy, routing, diagnostics, smoke, and soil gate all ok. Evidence: `outputs/phase49_staging10_observation_window.json`. |
| Phase 50 Staging 10% routed request smoke | complete | Verified in-bucket requests use runtime active planner and out-of-bucket requests fall back to legacy, without LLM/tool execution. Evidence: `outputs/phase50_staging10_routed_request_smoke.json`. |
| Phase 51 Staging 10% quasi-real task window | complete | Three quasi-real task classes passed: vector clip map, table-to-points map, and XGBoost raster prediction map. Outputs included artifact/map/raster/png/summary and no external downloads. Evidence: `outputs/phase51_staging10_quasi_real_task_window.json` and `outputs/phase51_staging10_short_window_quality_summary.json`. |
| Phase 52 Staging 10% observation hardening | complete | Added reusable staging observation gate: `core/agent_runtime/staging_observation_gate.py`, `scripts/run_agent_runtime_staging10_observation_gate.ps1`, and tests. Full gate passed with `ok=true`; commit `f0d3a69`. |
| Phase 53 Remote/real staging synchronization plan | planned | Do not increase exposure beyond 10% yet. Next rollout work should solidify remote staging migration, `.env`/service restart checklist, read-only admin exposure checks, recurring observation cadence, user-task metrics, latency, artifact/map output checks, external-download false-positive checks, soil moisture/GCP paths, and rollback triggers. |
| Phase 54 CI baseline stabilization | complete | Stabilized PR #3 CI on branch `codex/phase54-ci-baseline-stabilization`: curated Python gate, frontend fallback installer, doctor Python override, smoke service readiness/E2E same-step execution, peer/type dependency fixes. Remote CI passed. |
| Phase 55 CI dependency cache optimization | complete | Added low-risk package-manager cache policy: pip cache for Python jobs, npm cache already retained, Yarn fallback download cache added, and contract tests prevent caching `node_modules`/`.venv`. Commit `1a312b3`; PR #3 CI passed. |
| Phase 56 Remote/real staging sync checklist | complete | Added `docs/runbooks/agent-runtime-remote-staging-sync.md` and contract tests for remote staging config, restart/reload, read-only admin exposure checks, recurring observation cadence, real-task metrics, rollback triggers, and CI cache observation. No exposure increase or production traffic change. |
| Phase 57 CI layering and path-filter acceleration | complete | Added conservative CI concurrency, path filtering, docs-only contract checks, PR-default `smoke-light`, and manual/nightly `smoke-full` staging observation gates. Did not change runtime/staging exposure or production traffic. |
| Phase 58 Playwright browser cache | complete | Added low-risk Playwright browser binary cache for `smoke-light`, keyed by OS and `requirements.txt`, while preserving `python -m playwright install chromium` as the cache-miss fallback. Did not cache `node_modules` or `.venv`. |
| Phase 59 Final PR delivery audit | complete | Audited PR #3 merge readiness without merging main, raising exposure, or touching production. Added `docs/runbooks/pr3-final-delivery-audit.md` with PR status, changed scope, GitNexus risk, CI evidence, runtime/staging/soil moisture gate evidence, rollout boundaries, and merge-decision recommendation. |
| Phase 60A Knowledge seed refresh | complete | Added draft-only GIS/ISMN/soil-moisture XGBoost/GCP knowledge seed, manifest entry, contract tests, design spec, and implementation plan. No runtime routing, staging exposure, production traffic, ISMN download automation, or ArcPy dependency changes. |
| Phase 60B Post-merge staging observation preflight | complete | Ran safe post-merge preflight after Phase 60A: latest main CI success confirmed, local soil moisture/GCP recurring gate ok, and local staging10 observation gate ok. Did not deploy real staging, raise exposure, touch production, or alter routing. Real remote staging observation remains an explicit operator-confirmed action. |
| Phase 60C Built-in knowledge activation | complete | Activated short trusted built-in snippets for ISMN local archives, GCP uncertainty interpretation, and ArcGIS/ArcPy taxonomy boundaries. Kept runtime logic unchanged and preserved no ISMN auto-download, no ArcPy dependency, no exposure change, and no production traffic. |
| Phase 60D PR #4 delivery audit | complete | Added PR #4 knowledge activation delivery audit with current PR status, changed scope, GitNexus blast radius, local/remote validation evidence, knowledge activation boundaries, rollout boundaries, and ready-state recommendation. Did not mark ready, merge main, raise exposure, or touch production. |
| Phase 60E Goal completion audit | complete | Added goal-level completion audit showing current evidence satisfies local/PR deliverables, CI, docs/tests, gates, push, and clean worktree, while final completion remains blocked on explicit human decisions for PR ready/merge and real remote staging/exposure actions. |
| Phase 60F PR #4 ready/merge operator checklist | complete | Added operator checklist for PR #4 ready-state, merge preflight, merge command, post-merge local/readonly verification, real staging handoff, rollback verification, and forbidden actions. It does not mark ready, merge main, raise exposure, or touch production. |
| Phase 60G PR #4 ready-state publication | complete | After fresh pre-ready checks, marked PR #4 ready for review. CodeRabbit completed, PR remains open, non-draft, merge state CLEAN, and checks are green/skipped as designed. Did not merge main, raise exposure, touch real staging, or touch production. |
| Phase 61 CI full-smoke reproducibility | complete | PR #5 merged to `main` at `09aa54f`; sanitized CI fixtures and in-process staging gate env setup make manual/nightly `smoke-full` reproducible on fresh GitHub runners. Main CI `28371199539` passed; PR #5 manual full CI `28370463288` passed. |
| Phase 62 Real remote staging execution handoff | pending | Do not raise exposure yet. Next work requires operator-provided staging URL/host, safe admin token retrieval, service restart/reload method, and deployed config verification path before running the real remote staging checklist. |
