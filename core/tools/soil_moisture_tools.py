from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.tools import tool

from core.ismn_adapter import (
    import_ismn_soil_moisture_archive as _import_ismn_soil_moisture_archive,
    list_ismn_archives as _list_ismn_archives,
    profile_ismn_archive as _profile_ismn_archive,
    resolve_ismn_archive,
)
from core.tool_contracts import tool_result_error, tool_result_ok


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _tool_error(tool_name: str, inputs: dict[str, Any], result: dict[str, Any]) -> str:
    return tool_result_error(
        tool_name,
        inputs=inputs,
        error_code=str(result.get("error_code") or "ISMN_TOOL_FAILED"),
        error_title="ISMN tool failed",
        user_message=str(result.get("user_message") or "The ISMN tool could not complete."),
        technical_detail=str(result.get("technical_detail") or ""),
        diagnostics={key: value for key, value in result.items() if key not in {"ok", "technical_detail"}},
        next_actions=[str(item) for item in result.get("next_actions", []) if str(item).strip()],
    ).to_json()


def build_soil_moisture_tools(manager: Any) -> list[Any]:
    @tool
    def list_ismn_archives() -> str:
        """List local official ISMN zip archives from uploads, derived outputs, and local_library/data/ismn."""
        archives = _list_ismn_archives(manager)
        return tool_result_ok(
            "list_ismn_archives",
            outputs={"archives": archives, "archive_count": len(archives)},
            summary=f"Found {len(archives)} local ISMN archive(s).",
            next_actions=["Use profile_ismn_archive to inspect networks, stations, sensors, depths, and time ranges."],
        ).to_json()

    @tool
    def profile_ismn_archive(archive: str = "") -> str:
        """Profile a local ISMN archive without downloading data or exposing absolute paths."""
        inputs = {"archive": archive}
        path = resolve_ismn_archive(manager, archive)
        if path is None:
            return tool_result_error(
                "profile_ismn_archive",
                inputs=inputs,
                error_code="ISMN_ARCHIVE_NOT_FOUND",
                error_title="ISMN archive not found",
                user_message="No matching local ISMN archive was found.",
                next_actions=["Upload an official ISMN archive zip or place it under local_library/data/ismn."],
            ).to_json()
        result = _profile_ismn_archive(path)
        if not result.get("ok"):
            return _tool_error("profile_ismn_archive", inputs, result)
        return tool_result_ok(
            "profile_ismn_archive",
            inputs={"archive": Path(path).name},
            outputs={"profile": result.get("profile", {}), "archive": result.get("archive", {})},
            summary="Profiled the local ISMN archive.",
            next_actions=["Use import_ismn_soil_moisture_archive with explicit depth/time filters when needed."],
        ).to_json()

    @tool
    def import_ismn_soil_moisture_archive(
        archive: str = "",
        output_name: str = "ismn_soil_moisture",
        network: str = "",
        station: str = "",
        variable: str = "soil_moisture",
        depth_from: float | None = None,
        depth_to: float | None = None,
        start_date: str = "",
        end_date: str = "",
        aggregation: str = "daily",
        quality_policy: str = "good_or_usable_only",
    ) -> str:
        """Import an already-downloaded official ISMN archive into a soil-moisture observation table."""
        inputs = {
            "archive": archive,
            "output_name": output_name,
            "network": network,
            "station": station,
            "variable": variable,
            "depth_from": depth_from,
            "depth_to": depth_to,
            "start_date": start_date,
            "end_date": end_date,
            "aggregation": aggregation,
            "quality_policy": quality_policy,
        }
        path = resolve_ismn_archive(manager, archive)
        if path is None:
            return tool_result_error(
                "import_ismn_soil_moisture_archive",
                inputs=inputs,
                error_code="ISMN_ARCHIVE_NOT_FOUND",
                error_title="ISMN archive not found",
                user_message="No matching local ISMN archive was found.",
                next_actions=["Upload an official ISMN archive zip or place it under local_library/data/ismn."],
            ).to_json()
        result = _import_ismn_soil_moisture_archive(
            manager,
            path,
            output_name=output_name,
            network=network,
            station=station,
            variable=variable,
            depth_from=depth_from,
            depth_to=depth_to,
            start_date=start_date,
            end_date=end_date,
            aggregation=aggregation,
            quality_policy=quality_policy,
        )
        if not result.get("ok"):
            return _tool_error("import_ismn_soil_moisture_archive", inputs, result)
        return tool_result_ok(
            "import_ismn_soil_moisture_archive",
            inputs={**inputs, "archive": Path(path).name},
            outputs={key: value for key, value in result.items() if key not in {"ok", "warnings"}},
            warnings=[str(item) for item in result.get("warnings", [])],
            summary=f"Imported ISMN soil moisture observations to {result.get('dataset_name')}.",
            next_actions=["Add DEM, NDVI, LST, climate, soil, or land-cover feature data before training XGBoost."],
        ).to_json()

    return [list_ismn_archives, profile_ismn_archive, import_ismn_soil_moisture_archive]
