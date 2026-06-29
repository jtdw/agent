# Agent Knowledge Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a draft knowledge seed that aligns the agent knowledge base with current GIS, ISMN, soil-moisture XGBoost, and GeoConformal Prediction capabilities.

**Architecture:** Keep the change in the repository knowledge-seed layer: one new Markdown seed document, one manifest entry, focused contract tests, and planning updates. Do not modify runtime routing, Tool Cards, FastAPI, frontend, staging exposure, or production behavior.

**Tech Stack:** Markdown knowledge seeds, JSON manifest, Python pytest contract tests, PowerShell commands, GitNexus CLI.

---

## File Structure

- Create `docs/knowledge_seed/09_ismn_soil_moisture_gcp_reference.md`: draft reference document for ISMN local archives, soil-moisture modeling, XGBoost output contracts, GCP uncertainty, and GIS taxonomy boundaries.
- Modify `docs/knowledge_seed/manifest.json`: append the ninth seed document with import order, tags, retrieval questions, content hash, and review metadata.
- Modify `tests/test_knowledge_seed_docs.py`: expect the ninth file and verify retrieval routing for ISMN, GCP, spatial fallback, and ArcGIS/ArcPy taxonomy boundaries.
- Modify `.planning/langchain_agent_redesign/task_plan.md`: mark Phase 60A complete when implementation and validation pass.
- Modify `.planning/langchain_agent_redesign/findings.md`: add implementation findings and boundary decisions.
- Modify `.planning/langchain_agent_redesign/progress.md`: log RED/GREEN tests, verification commands, GitNexus result, commit, and push evidence.

## Task 1: Contract Test Red

**Files:**
- Modify: `tests/test_knowledge_seed_docs.py`

- [ ] **Step 1: Run GitNexus impact for existing edited test symbols**

Run:

```powershell
node .\.gitnexus\run.cjs impact test_seed_documents_have_draft_front_matter_manifest_and_queries --direction upstream
node .\.gitnexus\run.cjs impact test_seed_retrieval_questions_route_to_expected_reference_documents --direction upstream
```

Expected: LOW risk or no business-flow impact. If GitNexus reports HIGH or CRITICAL, stop and report before editing.

- [ ] **Step 2: Add failing expectations**

Update `EXPECTED_FILES` to include:

```python
"09_ismn_soil_moisture_gcp_reference.md",
```

Add retrieval cases to `test_seed_retrieval_questions_route_to_expected_reference_documents()`:

```python
"ISMN 本地 archive 如何导入土壤水分观测": "09_ismn_soil_moisture_gcp_reference.md",
"GCP interval width uncertainty map 如何解释": "09_ismn_soil_moisture_gcp_reference.md",
"空间坐标不足时 GCP 为什么回退 global split conformal": "09_ismn_soil_moisture_gcp_reference.md",
"ArcPy ArcGIS 是否意味着项目要新增 arcpy 依赖": "09_ismn_soil_moisture_gcp_reference.md",
```

Add a focused safety test:

```python
def test_ismn_gcp_seed_remains_draft_reference_only() -> None:
    path = SEED_DIR / "09_ismn_soil_moisture_gcp_reference.md"
    text = path.read_text(encoding="utf-8")
    assert "status: \"draft\"" in text
    assert "不得自动下载 ISMN 数据" in text
    assert "不新增 ArcPy 运行时依赖" in text
    assert "不得替代 Tool Cards、Plan Validator 或真实 ToolResult" in text
```

- [ ] **Step 3: Run RED**

Run:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_seed_docs.py -q
```

Expected: fail because `docs/knowledge_seed/09_ismn_soil_moisture_gcp_reference.md` and the manifest entry do not exist yet.

## Task 2: Knowledge Seed Green

**Files:**
- Create: `docs/knowledge_seed/09_ismn_soil_moisture_gcp_reference.md`
- Modify: `docs/knowledge_seed/manifest.json`
- Test: `tests/test_knowledge_seed_docs.py`

- [ ] **Step 1: Add the seed document**

Create the Markdown file with front matter:

```markdown
---
title: "ISMN、土壤水分 XGBoost 与 GCP 不确定性参考"
language: "zh-CN"
tags: ["ismn", "soil_moisture", "xgboost", "gcp", "geoconformal", "arcpy", "arcgis", "uncertainty", "土壤水分", "不确定性", "空间预测"]
applicable_scope: "ismn_soil_moisture_gcp_reference"
reliability: "high"
version: "2026-06-29.1"
status: "draft"
source: "project-code: core/tool_cards.py; core/data_semantics.py; core/ismn_adapter.py; core/ml/generic_xgboost.py; core/gcp_uncertainty.py; external-reference: ArcGIS Pro ArcPy; ISMN docs; GeoConformal Prediction"
---
```

The body must include sections for:

- Reference boundaries.
- ISMN local archive posture.
- Soil moisture workflow.
- XGBoost output contract.
- GCP uncertainty interpretation.
- ArcGIS/ArcPy taxonomy alignment.
- Retrieval test questions.

- [ ] **Step 2: Compute content hash**

Run:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath docs\knowledge_seed\09_ismn_soil_moisture_gcp_reference.md
```

Expected: output a SHA256 hash used in manifest as `sha256:<lowercase-hash>`.

- [ ] **Step 3: Append manifest entry**

Append a ninth document object with:

```json
{
  "file": "09_ismn_soil_moisture_gcp_reference.md",
  "title": "ISMN、土壤水分 XGBoost 与 GCP 不确定性参考",
  "import_order": 9,
  "status": "draft",
  "tags": ["ismn", "soil_moisture", "xgboost", "gcp", "geoconformal", "arcpy", "arcgis", "uncertainty", "土壤水分", "不确定性", "空间预测"],
  "applicable_scope": "ismn_soil_moisture_gcp_reference",
  "reliability": "high",
  "source": "project-code: core/tool_cards.py; core/data_semantics.py; core/ismn_adapter.py; core/ml/generic_xgboost.py; core/gcp_uncertainty.py; external-reference: ArcGIS Pro ArcPy; ISMN docs; GeoConformal Prediction",
  "retrieval_test_questions": [
    "ISMN 本地 archive 如何导入土壤水分观测？",
    "GCP interval width uncertainty map 如何解释？",
    "空间坐标不足时 GCP 为什么回退 global split conformal？",
    "ArcPy ArcGIS 是否意味着项目要新增 arcpy 依赖？"
  ],
  "content_hash": "sha256:<lowercase-hash>",
  "reviewed_at": "2026-06-29",
  "verified_against_code_revision": "6e4b299",
  "knowledge_type": "ismn_soil_moisture_gcp_reference",
  "owner": "system-knowledge-admin",
  "last_verified_by": "Codex",
  "version": "2026-06-29.1"
}
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_seed_docs.py -q
```

Expected: all knowledge seed tests pass.

## Task 3: Planning, Verification, Commit, Push

**Files:**
- Modify: `.planning/langchain_agent_redesign/task_plan.md`
- Modify: `.planning/langchain_agent_redesign/findings.md`
- Modify: `.planning/langchain_agent_redesign/progress.md`

- [ ] **Step 1: Update planning files**

Mark Phase 60A complete, keep Phase 60B planned, and record the knowledge-refresh boundaries:

- draft-only seed;
- no runtime routing change;
- no staging exposure change;
- no ArcPy dependency;
- no ISMN download automation;
- no production traffic.

- [ ] **Step 2: Run verification**

Run:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_seed_docs.py tests\test_ci_baseline_workflow.py tests\test_runtime_staging_remote_runbook.py -q
git diff --check
node .\.gitnexus\run.cjs detect-changes --scope compare --base-ref origin/main
```

Expected: pytest passes, `git diff --check` has no whitespace errors beyond known line-ending warnings, and GitNexus reports no runtime-flow impact or low risk.

- [ ] **Step 3: Commit and push**

Run:

```powershell
git status --short
git add -- docs\knowledge_seed\09_ismn_soil_moisture_gcp_reference.md docs\knowledge_seed\manifest.json tests\test_knowledge_seed_docs.py .planning\langchain_agent_redesign\task_plan.md .planning\langchain_agent_redesign\findings.md .planning\langchain_agent_redesign\progress.md docs\superpowers\plans\2026-06-29-agent-knowledge-refresh-implementation-plan.md
git commit -m "docs(knowledge): refresh ismn soil moisture gcp seed"
git push
```

Expected: commit and push succeed on `codex/phase60-post-merge-staging-observation`.

## Self-Review

- Spec coverage: the plan covers the new seed document, manifest entry, tests, planning updates, verification, commit, and push.
- Placeholder scan: no placeholder work remains; hash value is intentionally computed in Task 2 after the file exists.
- Type consistency: the file name and manifest scope are consistent across all tasks.
- Safety coverage: the plan preserves draft-only knowledge, no ArcPy dependency, no ISMN download automation, no runtime routing change, no exposure change, and no production traffic.
