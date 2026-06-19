from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain.tools import tool

from core.station_data import stm_archive_to_training_dataframe
from core.tool_contracts import tool_result_error, tool_result_ok
from core.tool_preconditions import validate_dataset_exists
from core.workflows.data_package import (
    build_data_package_profiles,
    dumps_result,
    ingest_data_package as _ingest_data_package,
    plan_data_package_analysis as _plan_data_package_analysis,
)
from core.workflows.stm_soil_moisture import run_stm_soil_moisture_xgboost_workflow as _run_stm_xgb_workflow


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _validation_error(tool_name: str, inputs: dict[str, Any], errors: list[dict[str, Any]]) -> str:
    return tool_result_error(
        tool_name,
        inputs=inputs,
        technical_detail=_json(errors),
        diagnostics={"validation_errors": errors},
        next_actions=["Check the dataset name and required parameters, then retry."],
    ).to_json()


def build_common_tools(manager: Any) -> list[Any]:
    @tool
    def workspace_status() -> str:
        """Return the current scoped workspace summary, datasets, artifacts, and recent activity."""
        return _json(
            {
                "summary": manager.workspace_summary(),
                "datasets": manager.list_datasets(),
                "artifacts": manager.list_artifacts()[:8],
                "recent_activity": manager.operation_log[:8],
            }
        )

    @tool
    def list_datasets() -> str:
        """List all datasets visible in the current user/session scope."""
        return manager.dataset_brief()

    @tool
    def inspect_zip_datasets(file_path: str) -> str:
        """List loadable dataset candidates inside a zip archive before choosing one."""
        return _json({"candidates": manager.inspect_zip_datasets(file_path)})

    @tool
    def load_dataset(file_path: str, dataset_name: str = "", zip_member: str = "") -> str:
        """Load a local dataset path into the current session workspace. For multi-dataset zip files, pass zip_member from inspect_zip_datasets."""
        loaded_name = manager.load_path(file_path=file_path, name=dataset_name or None, zip_member=zip_member)
        return f"Dataset loaded: {loaded_name}\n{manager.dataset_brief()}"

    @tool
    def ingest_data_package(file_path: str, user_goal: str = "", output_prefix: str = "") -> str:
        """Safely unpack a zip data package, load all supported datasets, profile them, and recommend an analysis plan."""
        return dumps_result(_ingest_data_package(manager, file_path, user_goal=user_goal, output_prefix=output_prefix))

    @tool
    def plan_data_package_analysis(user_goal: str = "") -> str:
        """Build an analysis plan from the current workspace dataset profiles and the user's goal."""
        profiles = build_data_package_profiles(manager)
        return dumps_result(_plan_data_package_analysis(profiles, user_goal))

    @tool
    def convert_stm_station_archive_to_training_table(
        archive_path: str,
        preferred_depth: str = "0.050000",
        year: str = "2019",
        output_name: str = "stm_soil_moisture_training",
        aggregate: str = "daily",
    ) -> str:
        """Convert an ISMN/SMN-SDR .stm station zip archive into a modeling-ready table dataset."""
        inputs = {
            "archive_path": archive_path,
            "preferred_depth": preferred_depth,
            "year": year,
            "output_name": output_name,
            "aggregate": aggregate,
        }
        try:
            df = stm_archive_to_training_dataframe(
                archive_path,
                preferred_depth=preferred_depth,
                year=year,
                aggregate=aggregate,
            )
            if df.empty:
                return tool_result_error(
                    "convert_stm_station_archive_to_training_table",
                    inputs=inputs,
                    error_code="STM_NO_VALID_ROWS",
                    error_title="No valid STM observations",
                    user_message="The station archive did not contain valid observations for the requested depth and year.",
                    diagnostics={"preferred_depth": preferred_depth, "year": year, "aggregate": aggregate},
                    next_actions=["Check the archive depth labels and year range, then retry with matching parameters."],
                ).to_json()
            saved_name = manager.put_table(output_name, df)
            record = manager.get(saved_name)
            target_col = "soil_moisture_mean" if aggregate.strip().lower() == "daily" else "soil_moisture"
            return tool_result_ok(
                "convert_stm_station_archive_to_training_table",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "row_count": int(len(df)),
                    "station_count": int(df["station_id"].nunique()) if "station_id" in df else 0,
                    "target_col": target_col,
                    "path": str(record.path),
                    "columns": list(df.columns),
                },
                artifacts=[
                    {
                        "artifact_id": f"dataset:{saved_name}",
                        "path": str(record.path),
                        "type": "dataset",
                        "title": f"{saved_name}.csv",
                        "description": "Modeling-ready soil moisture station training table converted from STM files.",
                        "quality_status": "created",
                        "preview_available": True,
                    }
                ],
                summary=f"Converted STM station archive to training table {saved_name} with {len(df)} rows.",
                diagnostics={
                    "preferred_depth": preferred_depth,
                    "year": year,
                    "aggregate": aggregate,
                    "source_archive": archive_path,
                },
                next_actions=[
                    "Use table_to_points to create station points.",
                    "Use batch_register_points_to_rasters to sample DEM/NDVI/LST or other raster features.",
                    "Use generic_xgboost_workflow with the reported target_col.",
                ],
            ).to_json()
        except Exception as exc:
            return tool_result_error(
                "convert_stm_station_archive_to_training_table",
                inputs=inputs,
                error_code="STM_CONVERSION_FAILED",
                error_title="STM conversion failed",
                user_message="Failed to convert the station archive into a training table.",
                technical_detail=f"{type(exc).__name__}: {exc}",
                next_actions=["Confirm the file is a zip archive containing ISMN/SMN-SDR .stm files."],
            ).to_json()

    @tool
    def run_stm_soil_moisture_xgboost_workflow(
        archive_path: str = "",
        raster_names: str = "",
        preferred_depth: str = "0.050000",
        year: str = "2019",
        output_prefix: str = "stm_soil_moisture",
        aggregate: str = "daily",
        min_samples: int = 8,
        encode_aspect_circular: bool = True,
    ) -> str:
        """Run STM station archive conversion, point creation, raster sampling, and conditional XGBoost modeling."""
        return _json(
            _run_stm_xgb_workflow(
                manager,
                archive_path=archive_path,
                raster_names=raster_names,
                preferred_depth=preferred_depth,
                year=year,
                output_prefix=output_prefix,
                aggregate=aggregate,
                min_samples=min_samples,
                encode_aspect_circular=encode_aspect_circular,
            )
        )

    @tool
    def describe_dataset(dataset_name: str) -> str:
        """Describe a dataset, including metadata, fields, preview rows, CRS, or document preview."""
        inputs = {"dataset_name": dataset_name}
        errors = validate_dataset_exists(manager, dataset_name)
        if errors:
            return _validation_error("describe_dataset", inputs, errors)
        try:
            record = manager.get(dataset_name)
            preview = None
            fields: list[str] = []
            if record.data_type in {"table", "vector"}:
                preview = manager.preview_table_rows(dataset_name, rows=5)
                fields = [str(col) for col in (record.meta.get("columns") or [])] if isinstance(record.meta, dict) else []
            elif record.data_type == "document":
                preview = manager.preview_document(dataset_name, max_chars=500)
            outputs = {
                "name": record.name,
                "type": record.data_type,
                "path": str(record.path),
                "meta": record.meta,
                "preview": preview,
            }
            return tool_result_ok(
                "describe_dataset",
                inputs=inputs,
                outputs=outputs,
                summary=f"Read dataset summary for {record.name}.",
                diagnostics={
                    "field_count": len(fields),
                    "fields": fields,
                    "dataset_type": record.data_type,
                    "crs": record.meta.get("crs") if isinstance(record.meta, dict) else None,
                },
                next_actions=["Use the detected fields, CRS, and missing values to choose mapping, processing, or modeling steps."],
            ).to_json()
        except Exception as exc:  # pragma: no cover - defensive wrapper
            return tool_result_error(
                "describe_dataset",
                inputs=inputs,
                error_code="TOOL_INTERNAL_ERROR",
                error_title="Tool execution failed",
                user_message="Failed to describe the dataset.",
                technical_detail=str(exc)[:1000],
            ).to_json()

    @tool
    def preview_table(dataset_name: str, rows: int = 8) -> str:
        """Preview rows from a table or vector attribute table."""
        return _json(manager.preview_table_rows(dataset_name, rows=rows))

    @tool
    def rename_dataset(dataset_name: str, new_name: str) -> str:
        """Rename a dataset in the current scoped workspace."""
        final_name = manager.rename_dataset(dataset_name, new_name)
        return f"Dataset renamed: {dataset_name} -> {final_name}"

    @tool
    def database_status() -> str:
        """Return SQLite workspace database status for the current user/session scope."""
        return _json(manager.database_status())

    @tool
    def list_database_objects() -> str:
        """List readonly database catalog entries and SQL tables."""
        return _json(manager.list_database_objects())

    @tool
    def list_pipeline_runs(limit: int = 10) -> str:
        """List recent workflow or model pipeline runs in the current scope."""
        return _json(manager.list_pipeline_runs(limit=limit))

    @tool
    def show_pipeline_run(run_id: str = "") -> str:
        """Show one pipeline run; defaults to the most recent run when run_id is empty."""
        if not run_id:
            runs = manager.list_pipeline_runs(limit=1)
            if not runs:
                return "No pipeline runs found."
            run_id = runs[0]["run_id"]
        detail = manager.pipeline_run_detail(run_id)
        if not detail:
            raise ValueError(f"Pipeline run not found: {run_id}")
        return _json(detail)

    @tool
    def sync_dataset_to_database(dataset_name: str) -> str:
        """Sync one supported dataset into the scoped SQLite workspace database."""
        result = manager.sync_dataset_to_database(dataset_name)
        manager.log_operation("Sync dataset to database", f"{dataset_name} -> {result.get('sql_table')}", "database")
        return _json(result)

    @tool
    def sync_all_to_database() -> str:
        """Sync all supported datasets into the scoped SQLite workspace database."""
        results = manager.sync_all_supported_to_database()
        manager.log_operation("Sync all datasets to database", f"count: {len(results)}", "database")
        return _json({"count": len(results), "items": results})

    @tool
    def query_workspace_database(sql: str, output_name: str = "") -> str:
        """Run a readonly SQLite query and optionally save the result as a new table dataset."""
        df = manager.query_database(sql)
        if output_name:
            saved_name = manager.put_table(output_name, df)
            manager.log_operation("Database query", f"output dataset: {saved_name}", "database")
            return f"Query completed: {len(df)} rows; result dataset: {saved_name}; path: {manager.get(saved_name).path}"
        manager.log_operation("Database query", f"returned {len(df)} rows", "database")
        return _json(df.head(200).replace({pd.NA: None}).to_dict(orient="records"))

    return [
        workspace_status,
        list_datasets,
        inspect_zip_datasets,
        load_dataset,
        ingest_data_package,
        plan_data_package_analysis,
        convert_stm_station_archive_to_training_table,
        run_stm_soil_moisture_xgboost_workflow,
        describe_dataset,
        preview_table,
        rename_dataset,
        database_status,
        list_database_objects,
        list_pipeline_runs,
        show_pipeline_run,
        sync_dataset_to_database,
        sync_all_to_database,
        query_workspace_database,
    ]
