# Agent Knowledge Refresh Design

Date: 2026-06-29
Status: approved-design

## Goal

Refresh the GIS agent knowledge seed so retrieval, planner context, and later staging observation match the project's current capabilities after the ISMN, soil-moisture XGBoost, GeoConformal Prediction, runtime, and staging-gate work.

This phase prepares reviewed draft knowledge. It does not activate new production knowledge, change FastAPI behavior, change frontend behavior, raise staging exposure, touch production traffic, or add external dependencies.

## Scope

Create a focused Phase 60A knowledge refresh before the post-merge staging observation phase:

- Add one new knowledge seed document for ISMN, soil moisture modeling, GCP uncertainty, and GIS workflow taxonomy.
- Update the knowledge seed manifest with draft metadata, retrieval questions, tags, and content hash.
- Add or update contract tests so future edits cannot silently remove the new source-boundary, ISMN, GCP, and GIS precondition guidance.
- Update `.planning/langchain_agent_redesign` to record Phase 60A and move post-merge staging observation to the next phase.

## External References

The references are used as domain and documentation context. They do not override project code, Tool Cards, Plan Validator, Product Catalog, or runtime gates.

- ArcGIS Pro ArcPy reference: ArcPy is treated as a GIS taxonomy reference for geoprocessing, mapping, Spatial Analyst, and Image Analyst domains, not as a runtime dependency.
- ArcGIS Pro XY Table To Point: use as supporting guidance that table-to-point conversion needs real x/y coordinate fields and an explicit coordinate system.
- ArcGIS Pro Zonal Statistics as Table: use as supporting guidance that zonal statistics summarize raster values by zone and produce a table-like result.
- ISMN documentation: use as supporting guidance for local `ISMN_Interface` style archive access, station/sensor metadata, depths, variables, and time ranges.
- GeoConformal Prediction article and companion repository: use as supporting guidance for model-agnostic spatial uncertainty, global split conformal fallback, spatial weighting when coordinates are available, and interval-map interpretation.

## Design

### Knowledge Seed Document

Add `docs/knowledge_seed/09_ismn_soil_moisture_gcp_reference.md`.

The document should cover:

- ISMN local archive posture: uploaded or local-library archives only; no automated login, download, cookie, token, or storage-state handling.
- ISMN metadata roles: network, station, sensor, depth range, variable, quality flag, coordinates, time range, instrument, and optional soil/land-cover/climate metadata.
- Soil moisture workflow routing: import observations, profile ambiguity, ask about depth/time filters when ambiguous, align feature rasters by space/time, train XGBoost, then run GCP only from real prediction/residual outputs.
- XGBoost output contract: prediction, residual, validation prediction/residual, validation method, fold or role columns, coordinate/time metadata, feature semantics, and random split limitations.
- GCP interpretation: absolute-residual nonconformity baseline, global split conformal as safe fallback, spatially weighted GCP only when coordinates and calibration support are sufficient, interval width and coverage metrics as real tool outputs only.
- GIS taxonomy alignment: ArcGIS/ArcPy is a reference vocabulary for common GIS operations, while the agent must still use existing registered tools and Tool Cards.

### Manifest Update

Update `docs/knowledge_seed/manifest.json`:

- Append the new document as import order 9.
- Keep status `draft`.
- Keep import policy review-first.
- Add retrieval questions for ISMN archive import, GCP uncertainty maps, spatial fallback, and ArcGIS/ArcPy reference boundaries.
- Store the SHA-256 content hash of the new document.

### Tests

Update `tests/test_knowledge_seed_docs.py`:

- Add the new expected file.
- Add retrieval routing cases for:
  - ISMN local archive import.
  - GCP interval width or uncertainty map.
  - spatial fallback to global split conformal.
  - ArcGIS/ArcPy as taxonomy, not a dependency.
- Add checks that the new document remains draft-only and includes no production activation language.

If implementation touches test functions, run GitNexus impact first for the edited test symbols.

### Runtime Boundary

Do not update `core/knowledge_base.py` built-in snippets in this phase unless tests show that seed-level retrieval cannot cover the intended cases. Built-in snippets are live code; seed documents are safer because they remain draft until an operator imports and reviews them.

Do not update Tool Cards unless a source exposes a mismatch with actual implemented tools. The current expected change is knowledge-only.

## Data Flow

The refreshed knowledge remains a document seed:

1. Maintainer reviews the seed document.
2. Admin imports it into capability config as draft.
3. Admin approves it to active only after review.
4. Runtime retrieval may then include it through `configured_knowledge()`.

Before approval, the seed document is repository documentation and test fixture only.

## Safety

- No staging exposure increase.
- No production traffic changes.
- No ISMN download automation.
- No credential, cookie, token, storage-state, or `.env` handling.
- No ArcPy dependency or ArcGIS runtime dependency.
- No claims that knowledge text can execute tools.
- No claims that external docs override project code or Product Catalog.

## Verification

Minimum verification after implementation:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_seed_docs.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_ci_baseline_workflow.py tests\test_runtime_staging_remote_runbook.py -q
node .\.gitnexus\run.cjs detect-changes --scope compare --base-ref origin/main
```

If only docs, manifest, tests, and planning files change, a low-risk or no-runtime-flow GitNexus result is expected.

## Rollout

Phase 60A should be completed and pushed before Phase 60B post-merge staging observation. Staging observation should then validate a codebase whose knowledge seed reflects current ISMN, XGBoost, GCP, and GIS workflow capabilities.

The Phase 60A commit does not authorize:

- raising staging exposure;
- touching production;
- changing authentication, billing, download safety, or artifact permissions;
- importing the new knowledge as active in a live environment.

## References

- https://pro.arcgis.com/ja/pro-app/latest/arcpy/main/arcgis-pro-arcpy-reference.htm
- https://pro.arcgis.com/en/pro-app/3.4/tool-reference/data-management/xy-table-to-point.htm
- https://pro.arcgis.com/en/pro-app/3.6/tool-reference/spatial-analyst/zonal-statistics-as-table.htm
- https://ismn.readthedocs.io/en/latest/
- https://ismn.readthedocs.io/en/latest/examples/interface.html
- https://arxiv.org/abs/2412.08661
- https://github.com/pengtum/geoconformal
