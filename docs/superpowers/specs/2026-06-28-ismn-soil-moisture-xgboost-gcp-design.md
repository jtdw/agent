# ISMN Soil Moisture XGBoost And GeoConformal Prediction Design

## Goal

Upgrade the soil-moisture modeling workflow so the agent can use local ISMN archives and local-library datasets as well-described scientific inputs, then run XGBoost prediction and GeoConformal Prediction (GCP) uncertainty analysis in a reproducible GIS workflow.

The workflow must help the agent know what each dataset is for: observation target, spatial feature, temporal feature, calibration set, prediction target, map layer, or derived artifact. The planner should use these semantics instead of guessing from filenames or prompt wording.

## External Basis

- The target GCP reference is the 2025 article `GeoConformal Prediction: A Model-Agnostic Framework for Measuring the Uncertainty of Spatial Prediction`, DOI `10.1080/24694452.2025.2516091`.
- ISMN data access stays authorization-respecting. The ISMN data site says in-situ soil moisture measurements are harmonized, quality-controlled, and made available online for free download, with sign-in/register flows on the data page.
- `TUW-GEO/ismn` is used as a local reader for already downloaded ISMN archive files. Its README documents `ISMN_Interface(<archive.zip>)`, sensor time series as pandas DataFrames, and station/sensor metadata such as depth, instrument, latitude, longitude, land cover, climate, and soil information.

## Non-Goals

- Do not automate login-protected ISMN download or store ISMN account credentials, cookies, storage state, or tokens.
- Do not replace the current LangChain runtime rollout work. This feature should be implemented after staging 5% is stable, or in a separate tool-upgrade phase.
- Do not remove existing `generic_xgboost_workflow`, `train_xgboost_fusion_model`, `geographical_conformal_prediction`, or `run_stm_soil_moisture_xgboost_workflow`. The first implementation should extend them compatibly.
- Do not send raw ISMN records, full coordinates, local file paths, or protected metadata to an external LLM.

## Architecture

Add a small data-semantics layer between dataset ingestion and planning:

1. `ISMN local archive adapter`
   - Reads user-uploaded ISMN zip archives and archives under `local_library/data/ismn/`.
   - Uses `ismn.interface.ISMN_Interface` when the optional `ismn` dependency is installed.
   - Falls back to a structured `ISMN_DEPENDENCY_MISSING` style error if not installed.

2. `Data semantic card registry`
   - Creates one semantic card per source archive, station table, raster feature dataset, training table, prediction table, calibration table, and GCP result.
   - Cards are stored in ordinary dataset metadata where possible and mirrored into a lightweight local catalog so planner/context code can query them without loading large data.

3. `Soil moisture training table builder`
   - Converts selected ISMN sensors to standard observation rows.
   - Aggregates by requested temporal grain.
   - Joins station observations with raster/table features already present in the workspace or local library.

4. `XGBoost workflow`
   - Reuses the existing XGBoost workflows.
   - Adds method metadata and validation strategy fields so outputs are ready for GCP.

5. `GeoConformal Prediction`
   - Extends the current GCP tool to report explicit method mode: global split conformal, spatially weighted GCP, or safe fallback.
   - Produces interval columns, uncertainty metrics, spatial diagnostics, maps, and a short method report.

## ISMN Archive Handling

Supported inputs:

- Uploaded official ISMN archive zip.
- Local-library archive at `local_library/data/ismn/**/*.zip`.
- Existing workspace archive copied from a prior upload.

The adapter should expose:

- `list_ismn_archives`
- `profile_ismn_archive`
- `import_ismn_soil_moisture_archive`

The import tool should support filters:

- network
- station
- variable, default `soil_moisture`
- depth range, for example 0-0.05 m
- start/end date
- quality flag policy, default keep good/usable values only
- aggregation: raw, hourly, daily, monthly

The output table should include at least:

- `network`
- `station`
- `sensor_id`
- `date_time` or aggregate date
- `soil_moisture`
- `soil_moisture_flag`
- `depth_from`
- `depth_to`
- `instrument`
- `lon`
- `lat`
- optional static metadata such as climate, land cover, soil class, sand/silt/clay, bulk density, field capacity, wilting point, and saturation when available.

## Data Semantic Cards

Each semantic card should be a JSON-safe object with this shape:

```json
{
  "schema_version": "gis-data-semantic-card/v1",
  "dataset_name": "ismn_daily_soil_moisture",
  "source_kind": "ismn_archive",
  "scientific_roles": ["soil_moisture_observation", "model_target_candidate", "gcp_calibration_candidate"],
  "variables": [
    {"name": "soil_moisture", "standard_name": "soil_moisture", "unit": "m3/m3", "role": "target"}
  ],
  "spatial": {"has_coordinates": true, "lon_col": "lon", "lat_col": "lat", "crs": "EPSG:4326"},
  "temporal": {"has_time": true, "time_col": "date_time", "start": "", "end": "", "frequency": "daily"},
  "quality": {"flag_columns": ["soil_moisture_flag"], "policy": "good_or_usable_only"},
  "modeling": {
    "can_train_xgboost": true,
    "can_calibrate_gcp": true,
    "can_validate_spatially": true,
    "recommended_target": "soil_moisture",
    "recommended_feature_cols": []
  },
  "lineage": {"source_archive_id": "", "created_by_tool": "import_ismn_soil_moisture_archive"}
}
```

Cards should be used by:

- context builder
- task planner
- runtime planner adapter
- workflow templates
- result-panel metadata

The agent should be able to answer: what this dataset measures, what unit it uses, whether it has coordinates/time/depth, whether it can be a target, whether it can be a feature, and whether it can be a GCP calibration set.

## Soil Moisture Workflow

The upgraded workflow is:

1. Resolve observation source from uploaded archive or local library.
2. Profile available networks, stations, sensors, variables, depths, and time ranges.
3. Select or ask for the target depth/time range when ambiguous.
4. Build an observation table with quality filtering and aggregation.
5. Resolve feature datasets from local library/workspace using semantic cards:
   - DEM and terrain derivatives
   - NDVI/EVI
   - LST or surface temperature
   - precipitation
   - land cover
   - soil texture/properties
   - climate zones
6. Sample raster features to station points and align by time when possible.
7. Build a training table with target, features, station id, coordinates, date/time, depth, and source metadata.
8. Train XGBoost with spatial or spatiotemporal validation when supported.
9. Run GCP using held-out or calibration predictions.
10. Register outputs as artifacts and semantic cards.

If only ISMN station data is available and no feature datasets exist, the workflow should stop after the training table and return `needs_feature_data` with next actions.

## XGBoost Method Updates

The XGBoost tools should keep current behavior but add explicit method fields:

- `validation_method`: random, group, date, spatial_block, spatiotemporal
- `cv_fold_column`
- `target_column`
- `prediction_column`
- `cv_prediction_column`
- `residual_column`
- `coordinate_columns`
- `time_column`
- `feature_semantics`
- `training_data_semantic_card`

Default validation priority:

1. Spatiotemporal validation when valid time and coordinates exist.
2. Spatial block validation when coordinates exist.
3. Group validation when station/network groups exist.
4. Date holdout when time exists.
5. Random split with warning when nothing else is possible.

For soil moisture workflows, station id or network/station should not be used as a predictive feature by default. They may be used for grouping, diagnostics, and plots.

## GeoConformal Prediction Updates

The GCP tool should align with a model-agnostic spatial uncertainty workflow:

- Input is a calibration/prediction table with observed values, predictions, and optional coordinates/time/folds.
- Nonconformity score defaults to absolute residual for regression.
- Global split conformal is the safe baseline.
- Spatially adaptive GCP uses distances from target points to calibration points to weight calibration scores.
- If coordinates are missing or insufficient, the tool must fall back to global split conformal and say so.

Outputs:

- `prediction_interval_lower`
- `prediction_interval_upper`
- `interval_width`
- `gcp_radius` or local quantile
- `covered`
- `method`
- `alpha`
- `target_coverage`
- `empirical_coverage`
- `mean_interval_width`
- `median_interval_width`
- `interval_score`
- coverage and width by fold/block when available

Visual outputs:

- interval-width spatial map when coordinates exist
- prediction interval plot
- coverage plot
- interval-width histogram
- optional block coverage chart

The result semantic card should mark the table as:

- `prediction_with_uncertainty`
- `gcp_result`
- `map_ready` when coordinates are available
- `calibration_diagnostics`

## Planner Behavior

The planner should prefer semantic-card evidence over prompt guesses.

Examples:

- If a user asks to train a soil moisture model and an ISMN observation card exists, use it as a target source.
- If several depths exist, ask for the depth unless the user already specified one.
- If observation data exists but no feature datasets exist, run import/training-table steps only and ask for feature rasters.
- If prediction outputs exist and GCP is requested, route to `geographical_conformal_prediction`.
- If the user asks for uncertainty maps and coordinates are missing, explain that only global intervals can be produced unless spatial coordinates are added.

The runtime active planner should receive only sanitized semantic summaries: dataset names, roles, variable names, units, row counts, coordinate/time availability, and candidate tool names. It must not receive raw rows, full local paths, credentials, cookies, or token-like metadata.

## Local Library Catalog

Local-library items should gain a manifest or derived catalog with:

- `library_id`
- title and short description
- source and license notes
- dataset type
- spatial/temporal coverage
- variables and units
- scientific roles
- recommended tools
- required preprocessing
- data quality limitations

The agent should use this catalog to answer "what data do I have?" and to plan workflows using local assets without loading all files.

## Error Handling

Expected structured errors:

- `ISMN_ARCHIVE_NOT_FOUND`
- `ISMN_DEPENDENCY_MISSING`
- `ISMN_ARCHIVE_UNSUPPORTED`
- `ISMN_SENSOR_FILTER_EMPTY`
- `ISMN_DEPTH_AMBIGUOUS`
- `SOIL_FEATURE_DATA_MISSING`
- `SPATIOTEMPORAL_VALIDATION_UNAVAILABLE`
- `GCP_COORDINATES_MISSING_GLOBAL_FALLBACK`
- `GCP_CALIBRATION_TOO_SMALL`

Errors should include `reason`, `next_actions`, and safe diagnostics. They should never include absolute file paths, cookies, tokens, or raw user credentials.

## Testing

Add focused tests before implementation:

- ISMN archive fixture import creates a table and semantic card.
- Local-library ISMN archive discovery works without upload.
- Missing `ismn` dependency returns a structured error.
- Multiple depths trigger clarification instead of arbitrary selection.
- Soil moisture workflow stops with `needs_feature_data` when only observations exist.
- Soil moisture workflow builds training data when raster features exist.
- XGBoost output includes validation method, CV prediction column, residuals, semantic-card metadata, and artifacts.
- GCP falls back to global split conformal without coordinates.
- GCP uses spatially adaptive mode with valid coordinates.
- GCP registers prediction intervals, metrics, maps, and semantic cards.
- Planner selects ISMN observation data and local-library feature data from semantic cards.
- Sanitization tests prove runtime planner context does not leak raw rows, absolute paths, cookies, tokens, or credentials.

## Implementation Phases

1. Add semantic-card schema and local-library catalog helpers.
2. Add ISMN local archive profiling/import tools behind optional dependency checks.
3. Upgrade STM soil-moisture workflow to consume semantic cards and ISMN outputs.
4. Add XGBoost method metadata and stronger spatial/spatiotemporal validation diagnostics.
5. Upgrade GCP outputs and diagnostics to support explicit spatially adaptive evidence.
6. Wire planner/tool cards/runtime context to use semantic summaries.
7. Add admin/read-only diagnostics for data semantic cards if useful.
8. Run focused tests, active smoke, and opt-in LLM coordinator smoke before any rollout expansion.

## Rollout

Keep this feature separate from the active-runtime exposure ladder. Recommended order:

1. Finish or hold Phase 38 staging exposure decision.
2. Implement this as a new GIS tool-upgrade phase.
3. Run local tool tests and deterministic active smoke.
4. Run opt-in LLM coordinator smoke for:
   - ISMN import
   - soil moisture training table
   - XGBoost training
   - GCP uncertainty analysis
5. Only then consider exposing the new workflow to broader staging traffic.

## Open Assumptions

- ISMN official data files are provided by the user or placed in the local library.
- The `ismn` package may be optional and should not become a hard startup dependency until package/install impact is reviewed.
- Existing project artifacts and result panels can display the first version of GCP outputs without a major frontend redesign.
- GCP implementation should begin with regression/absolute-residual intervals. Classification uncertainty can be a later phase.

## References

- DOI: https://doi.org/10.1080/24694452.2025.2516091
- Crossref metadata: https://api.crossref.org/works/10.1080/24694452.2025.2516091
- ISMN data page: https://ismn.earth/en/data/
- TUW-GEO ismn: https://github.com/TUW-GEO/ismn
- ismn documentation: https://ismn.readthedocs.io/en/latest/
