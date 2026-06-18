from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain.tools import tool

from core.tool_contracts import tool_result_error, tool_result_ok
from core.tool_preconditions import validate_dataset_exists


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
    def load_dataset(file_path: str, dataset_name: str = "") -> str:
        """Load a local dataset path into the current session workspace."""
        loaded_name = manager.load_path(file_path=file_path, name=dataset_name or None)
        return f"Dataset loaded: {loaded_name}\n{manager.dataset_brief()}"

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
        load_dataset,
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

