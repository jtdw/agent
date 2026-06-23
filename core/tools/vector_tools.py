from __future__ import annotations

from typing import Any

from core.tools import vector_helpers as _helpers

VECTOR_TOOL_NAMES = {
    'vector_filter',
    'vector_buffer',
    'vector_clip_by_vector',
    'vector_overlay',
    'vector_dissolve',
    'vector_spatial_join',
    'reproject_vector',
    'create_centroids',
    'calculate_geometry_fields',
    'join_attributes',
    'summarize_points_within_polygons',
}

_LEGACY_DEPENDENCIES = (
    'Any',
    'ArtifactInfo',
    'CRS',
    '_build_mask_from_query',
    '_align_crs',
    '_estimate_projected_gdf',
    '_prepare_join_frame',
    '_tool_error_from_validation',
    '_tool_internal_error',
    'gpd',
    'pd',
    'rasterio',
    'tool',
    'tool_result_error',
    'tool_result_ok',
    'uuid4',
    'validate_crs',
    'validate_dataset_exists',
    'validate_geometry_type',
    'validate_numeric_fields',
    'validate_output_path',
    'validate_raster_readable',
    'validate_required_fields',
    'validate_vector_readable',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)

def build_vector_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    @tool
    def vector_filter(dataset_name: str, expression: str, output_name: str) -> str:
        """按属性表达式筛选矢量数据，例如 expression='POP > 1000'。"""
        inputs = {"dataset_name": dataset_name, "expression": expression, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not str(expression or "").strip():
            errors.append(
                {
                    "error_code": "VECTOR_FILTER_EXPRESSION_REQUIRED",
                    "error_title": "缺少筛选表达式",
                    "user_message": "请提供明确的属性筛选表达式，例如 POP > 1000。",
                    "diagnostics": {},
                    "next_actions": ["指定 expression，并确保字段名来自真实矢量属性表。"],
                }
            )
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("vector_filter", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            mask = _build_mask_from_query(gdf.drop(columns="geometry", errors="ignore"), str(expression), "vector_filter.expression")
            filtered = gdf.loc[mask].copy()
            saved_name = manager.put_vector(output_name, filtered)
            record = manager.get(saved_name)
            manager.log_operation("矢量筛选", f"{dataset_name} -> {saved_name} | 条件: {expression}", "analysis")
            warnings_list = ["筛选结果为空，请检查表达式或字段取值。"] if filtered.empty else []
            return tool_result_ok(
                "vector_filter",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(filtered)), "path": str(record.path), "expression": expression},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(record.path),
                        type="dataset",
                        title=f"{saved_name} filtered vector",
                        description=f"{dataset_name} 按属性表达式筛选后的矢量结果。",
                        quality_status="empty" if filtered.empty else "created",
                        preview_available=False,
                    )
                ],
                map_layers=[{"layer_id": f"dataset_{saved_name.lower()}", "name": saved_name, "dataset_name": saved_name, "type": "vector"}],
                summary=f"矢量筛选完成，结果数据集 {saved_name}，要素数 {len(filtered)}。",
                diagnostics={
                    "source_dataset": dataset_name,
                    "source_count": int(len(gdf)),
                    "result_count": int(len(filtered)),
                    "available_fields": [str(col) for col in gdf.columns if str(col) != "geometry"],
                },
                warnings=warnings_list,
                next_actions=["检查筛选结果数量和属性字段。", "可继续用于裁剪、空间连接、制图或导出。"],
            ).to_json()
        except Exception as exc:
            return tool_result_error(
                "vector_filter",
                inputs=inputs,
                error_code="VECTOR_FILTER_EXPRESSION_INVALID",
                error_title="筛选表达式无效",
                user_message="筛选表达式无法安全解析或字段不存在，请检查字段名、比较符和取值。",
                diagnostics={"error_type": type(exc).__name__},
                next_actions=["使用真实字段名和简单比较表达式，例如 POP > 1000 或 type == 'river'。"],
            ).to_json()


    @tool
    def vector_buffer(dataset_name: str, distance: float, output_name: str, unit: str = "meter") -> str:
        """对矢量数据进行缓冲区分析。distance 单位为图层投影坐标系单位，若原始数据为经纬度则会自动估计 UTM 投影。"""
        inputs = {"dataset_name": dataset_name, "distance": distance, "output_name": output_name, "unit": unit}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        try:
            distance_value = float(distance)
            if distance_value <= 0:
                raise ValueError("distance must be positive")
        except Exception:
            return tool_result_error(
                "vector_buffer",
                inputs=inputs,
                error_code="BUFFER_DISTANCE_INVALID",
                error_title="Invalid buffer distance",
                user_message="Buffer distance must be a positive number.",
                diagnostics={"distance": distance},
                next_actions=["Provide a positive buffer distance before running buffer analysis."],
            ).to_json()
        unit_value = str(unit or "meter").strip().lower()
        if unit_value not in {"meter", "metre", "m"}:
            return tool_result_error(
                "vector_buffer",
                inputs=inputs,
                error_code="BUFFER_UNIT_UNSUPPORTED",
                error_title="缓冲区单位不支持",
                user_message="当前缓冲区工具只支持米制距离，请使用 unit=meter。",
                diagnostics={"allowed": ["meter"], "received": unit},
                next_actions=["请明确距离单位为 meter，或先将数据重投影到目标投影坐标系后再处理。"],
            ).to_json()
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("vector_buffer", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            projected, used_crs = _estimate_projected_gdf(gdf)
            buffered = projected.copy()
            buffered["geometry"] = projected.buffer(distance_value)
            buffered = buffered.to_crs(gdf.crs)
            saved_name = manager.put_vector(output_name, buffered)
            record = manager.get(saved_name)
            manager.log_operation("缓冲区分析", f"{dataset_name} -> {saved_name} | 距离: {distance_value}", "analysis")
            warnings_list = ["Buffer result is empty; check source geometry and distance."] if buffered.empty else []
            return tool_result_ok(
                "vector_buffer",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(buffered)),
                    "path": str(record.path),
                    "distance": distance_value,
                    "unit": "meter",
                    "processing_crs": used_crs,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"Buffer result from {dataset_name}.",
                        quality_status="empty" if buffered.empty else "ok",
                        preview_available=True,
                    )
                ],
                map_layers=[{"layer_id": f"dataset_{saved_name.lower()}", "name": saved_name, "dataset_name": saved_name, "type": "vector"}],
                summary=f"Created buffer dataset {saved_name} with {len(buffered)} features.",
                diagnostics={
                    "source_dataset": dataset_name,
                    "source_count": int(len(gdf)),
                    "result_count": int(len(buffered)),
                    "source_crs": str(gdf.crs),
                    "processing_crs": used_crs,
                    "distance_unit": "meter",
                },
                warnings=warnings_list,
                next_actions=["Inspect the buffer result, then continue with clipping, overlay, mapping, or export."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_buffer", inputs, exc)


    @tool
    def vector_clip_by_vector(dataset_name: str, clip_name: str, output_name: str) -> str:
        """使用一个矢量图层裁剪另一个矢量图层，常用于按研究区裁剪道路、点位或行政区。"""
        inputs = {"dataset_name": dataset_name, "clip_name": clip_name, "output_name": output_name}
        errors = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_dataset_exists(manager, clip_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_vector_readable(manager, clip_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_crs(manager, clip_name))
        if errors:
            return _tool_error_from_validation("vector_clip_by_vector", inputs, errors)
        try:
            source = manager.get_vector(dataset_name)
            clipper = manager.get_vector(clip_name)
            source, clipper = _align_crs(source, clipper)
            clipped = gpd.clip(source, clipper)
            saved_name = manager.put_vector(output_name, clipped)
            output_path = manager.get(saved_name).path
            manager.log_operation("矢量裁剪", f"{dataset_name} by {clip_name} -> {saved_name}", "analysis")
            warnings_list = ["裁剪结果为空，请检查两个图层是否相交。"] if clipped.empty else []
            return tool_result_ok(
                "vector_clip_by_vector",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(clipped)), "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} clipped vector",
                        description=f"{dataset_name} 被 {clip_name} 裁剪后的矢量结果。",
                        quality_status="empty" if clipped.empty else "created",
                        preview_available=False,
                    )
                ],
                summary=f"矢量裁剪完成，结果数据集 {saved_name}，要素数 {len(clipped)}。",
                diagnostics={"source_count": int(len(source)), "clip_count": int(len(clipper)), "result_count": int(len(clipped)), "crs": str(source.crs)},
                warnings=warnings_list,
                next_actions=["检查裁剪结果范围和要素数量。", "如结果为空，请确认两个图层坐标系和空间范围。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_clip_by_vector", inputs, exc)
        source = manager.get_vector(dataset_name)
        clipper = manager.get_vector(clip_name)
        source, clipper = _align_crs(source, clipper)
        clipped = gpd.clip(source, clipper)
        saved_name = manager.put_vector(output_name, clipped)
        manager.log_operation("矢量裁剪", f"{dataset_name} by {clip_name} -> {saved_name}", "analysis")
        return f"矢量裁剪完成，结果: {saved_name}，要素数量: {len(clipped)}，保存路径: {manager.get(saved_name).path}"


    @tool
    def vector_overlay(dataset_name: str, overlay_name: str, how: str, output_name: str) -> str:
        """执行常见矢量叠加分析。how 可选 intersection、union、difference、identity、symmetric_difference。"""
        allowed = {"intersection", "union", "difference", "identity", "symmetric_difference"}
        inputs = {
            "dataset_name": dataset_name,
            "overlay_name": overlay_name,
            "how": how,
            "output_name": output_name,
        }
        if how not in allowed:
            return tool_result_error(
                "vector_overlay",
                inputs=inputs,
                error_code="OVERLAY_MODE_UNSUPPORTED",
                error_title="叠加方式不支持",
                user_message=f"how 必须是 {', '.join(sorted(allowed))} 之一。",
                diagnostics={"allowed": sorted(allowed), "received": how},
                next_actions=["请选择一种受支持的叠加方式后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_dataset_exists(manager, overlay_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_vector_readable(manager, overlay_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_crs(manager, overlay_name))
        if errors:
            return _tool_error_from_validation("vector_overlay", inputs, errors)

        try:
            left = manager.get_vector(dataset_name)
            right = manager.get_vector(overlay_name)
            left, right = _align_crs(left, right)
            result = gpd.overlay(left, right, how=how)
            saved_name = manager.put_vector(output_name, result)
            record = manager.get(saved_name)
            warnings_list = ["叠加结果为空，请检查两个图层是否存在空间重叠或叠加方式是否合适。"] if result.empty else []
            manager.log_operation("矢量叠加", f"{dataset_name} {how} {overlay_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_overlay",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(result)),
                    "path": str(record.path),
                    "how": how,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} {how} {overlay_name} overlay result",
                        quality_status="empty" if result.empty else "ok",
                        preview_available=True,
                    )
                ],
                summary=f"已完成 {dataset_name} 与 {overlay_name} 的 {how} 叠加，输出 {saved_name}，要素数 {len(result)}。",
                diagnostics={
                    "left_count": int(len(left)),
                    "right_count": int(len(right)),
                    "result_count": int(len(result)),
                    "how": how,
                    "crs": str(left.crs) if left.crs is not None else None,
                },
                warnings=warnings_list,
                next_actions=["可继续对叠加结果制图、统计属性字段，或检查空结果区域。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_overlay", inputs, exc)
        if how not in allowed:
            raise ValueError(f"how 必须是 {sorted(allowed)} 之一")
        left = manager.get_vector(dataset_name)
        right = manager.get_vector(overlay_name)
        left, right = _align_crs(left, right)
        result = gpd.overlay(left, right, how=how)
        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("矢量叠加", f"{dataset_name} {how} {overlay_name} -> {saved_name}", "analysis")
        return f"矢量叠加完成，方式: {how}，结果: {saved_name}，要素数量: {len(result)}，保存路径: {manager.get(saved_name).path}"


    @tool
    def vector_dissolve(dataset_name: str, by_field: str, output_name: str) -> str:
        """按字段融合矢量面或线，适合按分类字段汇总区域。"""
        inputs = {"dataset_name": dataset_name, "by_field": by_field, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_required_fields(manager, dataset_name, [by_field]))
        if errors:
            return _tool_error_from_validation("vector_dissolve", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            dissolved = gdf.dissolve(by=by_field).reset_index()
            saved_name = manager.put_vector(output_name, dissolved)
            record = manager.get(saved_name)
            manager.log_operation("矢量融合", f"{dataset_name} by {by_field} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_dissolve",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(dissolved)), "path": str(record.path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} dissolved by {by_field}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已按字段 {by_field} 融合 {dataset_name}，输出 {saved_name}，要素数 {len(dissolved)}。",
                diagnostics={"source_count": int(len(gdf)), "result_count": int(len(dissolved)), "by_field": by_field, "crs": str(gdf.crs)},
                next_actions=["可继续对融合结果制图、叠加分析或导出。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_dissolve", inputs, exc)
        gdf = manager.get_vector(dataset_name)
        if by_field not in gdf.columns:
            raise ValueError(f"字段不存在: {by_field}。可用字段: {list(gdf.columns)}")
        dissolved = gdf.dissolve(by=by_field).reset_index()
        saved_name = manager.put_vector(output_name, dissolved)
        manager.log_operation("矢量融合", f"{dataset_name} by {by_field} -> {saved_name}", "analysis")
        return f"融合完成，结果: {saved_name}，要素数量: {len(dissolved)}，保存路径: {manager.get(saved_name).path}"


    @tool
    def vector_spatial_join(target_name: str, join_name: str, predicate: str, output_name: str, how: str = "left", field_conflict_strategy: str = "suffix") -> str:
        """对两个矢量图层执行空间连接。predicate 常用 intersects、within、contains、touches、overlaps。"""
        allowed = {"intersects", "within", "contains", "touches", "overlaps", "crosses"}
        inputs = {"target_name": target_name, "join_name": join_name, "predicate": predicate, "output_name": output_name, "how": how, "field_conflict_strategy": field_conflict_strategy}
        if predicate not in allowed:
            return tool_result_error(
                "vector_spatial_join",
                inputs=inputs,
                error_code="SPATIAL_PREDICATE_UNSUPPORTED",
                error_title="空间关系不支持",
                user_message=f"predicate 必须是 {', '.join(sorted(allowed))} 之一。",
                diagnostics={"allowed": sorted(allowed), "received": predicate},
                next_actions=["请选择一种受支持的空间关系后重试。"],
            ).to_json()
        if how not in {"left", "right", "inner"}:
            return tool_result_error(
                "vector_spatial_join",
                inputs=inputs,
                error_code="JOIN_MODE_UNSUPPORTED",
                error_title="连接方式不支持",
                user_message="how 必须是 left、right 或 inner。",
                diagnostics={"allowed": ["inner", "left", "right"], "received": how},
                next_actions=["请选择 left、right 或 inner 后重试。"],
            ).to_json()
        conflict_strategy = str(field_conflict_strategy or "suffix").strip().lower()
        if conflict_strategy not in {"suffix"}:
            return tool_result_error(
                "vector_spatial_join",
                inputs=inputs,
                error_code="FIELD_CONFLICT_STRATEGY_UNSUPPORTED",
                error_title="字段冲突策略不支持",
                user_message="当前空间连接只支持 suffix 字段冲突策略。",
                diagnostics={"allowed": ["suffix"], "received": field_conflict_strategy},
                next_actions=["请使用 field_conflict_strategy=suffix 后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, target_name))
        errors.extend(validate_dataset_exists(manager, join_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, target_name))
            errors.extend(validate_vector_readable(manager, join_name))
            errors.extend(validate_crs(manager, target_name))
            errors.extend(validate_crs(manager, join_name))
        if errors:
            return _tool_error_from_validation("vector_spatial_join", inputs, errors)
        try:
            target = manager.get_vector(target_name)
            join_gdf = manager.get_vector(join_name)
            target, join_gdf = _align_crs(target, join_gdf)
            joined = gpd.sjoin(target, join_gdf, how=how, predicate=predicate, lsuffix="target", rsuffix="join")
            if "index_right" in joined.columns:
                joined = joined.drop(columns=["index_right"])
            saved_name = manager.put_vector(output_name, joined)
            record = manager.get(saved_name)
            manager.log_operation("空间连接", f"{target_name} {predicate} {join_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_spatial_join",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(joined)), "path": str(record.path), "predicate": predicate, "how": how},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{target_name} {predicate} {join_name} spatial join result",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                map_layers=[{"layer_id": f"dataset_{saved_name.lower()}", "name": saved_name, "dataset_name": saved_name, "type": "vector"}],
                summary=f"已完成 {target_name} 与 {join_name} 的空间连接，输出 {saved_name}，要素数 {len(joined)}。",
                diagnostics={
                    "target_count": int(len(target)),
                    "join_count": int(len(join_gdf)),
                    "result_count": int(len(joined)),
                    "predicate": predicate,
                    "how": how,
                    "crs": str(target.crs),
                    "field_conflict_strategy": conflict_strategy,
                    "output_fields": [str(col) for col in joined.columns],
                },
                next_actions=["可继续统计连接结果、制图或导出。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_spatial_join", inputs, exc)
        if predicate not in allowed:
            raise ValueError(f"predicate 必须是 {sorted(allowed)} 之一")
        target = manager.get_vector(target_name)
        join_gdf = manager.get_vector(join_name)
        target, join_gdf = _align_crs(target, join_gdf)
        joined = gpd.sjoin(target, join_gdf, how=how, predicate=predicate)
        if "index_right" in joined.columns:
            joined = joined.drop(columns=["index_right"])
        saved_name = manager.put_vector(output_name, joined)
        manager.log_operation("空间连接", f"{target_name} {predicate} {join_name} -> {saved_name}", "analysis")
        return f"空间连接完成，结果: {saved_name}，连接方式: {how}，空间关系: {predicate}，保存路径: {manager.get(saved_name).path}"


    @tool
    def reproject_vector(dataset_name: str, target_crs: str, output_name: str) -> str:
        """将矢量数据重投影到目标坐标系，例如 EPSG:3857 或 EPSG:4326。"""
        inputs = {"dataset_name": dataset_name, "target_crs": target_crs, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        target_crs_value = str(target_crs or "").strip()
        try:
            if not target_crs_value:
                raise ValueError("target CRS is required")
            CRS.from_user_input(target_crs_value)
        except Exception as exc:
            return tool_result_error(
                "reproject_vector",
                inputs=inputs,
                error_code="TARGET_CRS_INVALID",
                error_title="Invalid target CRS",
                user_message=f"Target CRS {target_crs!r} is not a valid CRS identifier.",
                diagnostics={"target_crs": target_crs, "exception_type": type(exc).__name__},
                next_actions=["Use an EPSG code such as EPSG:4326 or EPSG:3857."],
                technical_detail=f"{type(exc).__name__}: {exc}",
            ).to_json()
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("reproject_vector", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            reproj = gdf.to_crs(target_crs_value)
            saved_name = manager.put_vector(output_name, reproj)
            record = manager.get(saved_name)
            manager.log_operation("矢量重投影", f"{dataset_name} -> {saved_name} | {target_crs_value}", "analysis")
            return tool_result_ok(
                "reproject_vector",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(reproj)),
                    "path": str(record.path),
                    "source_crs": str(gdf.crs),
                    "target_crs": target_crs_value,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} reprojected to {target_crs_value}.",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"Reprojected {dataset_name} to {target_crs_value} as {saved_name}.",
                diagnostics={"source_count": int(len(gdf)), "result_count": int(len(reproj)), "source_crs": str(gdf.crs), "target_crs": target_crs_value},
                next_actions=["Use the reprojected dataset for overlay, clipping, mapping, or export."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("reproject_vector", inputs, exc)


    @tool
    def create_centroids(dataset_name: str, output_name: str) -> str:
        """将面或线图层转为质心点图层，常用于区域代表点、标注点和后续点分析。"""
        gdf = manager.get_vector(dataset_name)
        projected, used_crs = _estimate_projected_gdf(gdf)
        centroid_proj = projected.copy()
        centroid_proj["geometry"] = projected.centroid
        centroids = centroid_proj.to_crs(gdf.crs)
        saved_name = manager.put_vector(output_name, centroids)
        manager.log_operation("生成质心", f"{dataset_name} -> {saved_name}", "analysis")
        return f"质心点图层已生成: {saved_name}，处理投影: {used_crs}，保存路径: {manager.get(saved_name).path}"


    @tool
    def calculate_geometry_fields(
        dataset_name: str,
        output_name: str,
        area_field: str = "area_value",
        length_field: str = "length_value",
        centroid_x_field: str = "centroid_x",
        centroid_y_field: str = "centroid_y",
    ) -> str:
        """为矢量图层计算面积、长度和质心坐标字段，适合论文统计、字段补充和制表。"""
        gdf = manager.get_vector(dataset_name)
        projected, used_crs = _estimate_projected_gdf(gdf)
        enriched = gdf.copy()
        enriched[area_field] = projected.area
        enriched[length_field] = projected.length
        centroids = projected.centroid
        enriched[centroid_x_field] = centroids.x
        enriched[centroid_y_field] = centroids.y
        saved_name = manager.put_vector(output_name, enriched)
        manager.log_operation("几何字段计算", f"{dataset_name} -> {saved_name}", "analysis")
        return (
            f"几何字段已写入: {saved_name}，面积字段: {area_field}，长度字段: {length_field}，"
            f"质心字段: {centroid_x_field}/{centroid_y_field}，处理投影: {used_crs}，保存路径: {manager.get(saved_name).path}"
        )


    @tool
    def join_attributes(left_name: str, right_name: str, left_key: str, right_key: str, output_name: str) -> str:
        """按字段把表格或矢量属性连接到另一张表或图层上，适合行政区属性补充、统计结果回连等场景。"""
        inputs = {
            "left_name": left_name,
            "right_name": right_name,
            "left_key": left_key,
            "right_key": right_key,
            "output_name": output_name,
        }
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, left_name))
        errors.extend(validate_dataset_exists(manager, right_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if errors:
            return _tool_error_from_validation("join_attributes", inputs, errors)
        try:
            left_obj, left_type = _prepare_join_frame(left_name, manager)
            right_obj, _ = _prepare_join_frame(right_name, manager)
        except Exception as exc:
            return _tool_internal_error("join_attributes", inputs, exc)

        missing: list[str] = []
        if left_key not in left_obj.columns:
            missing.append(str(left_key))
        if right_key not in right_obj.columns:
            missing.append(str(right_key))
        if missing:
            return tool_result_error(
                "join_attributes",
                inputs=inputs,
                error_code="FIELD_NOT_FOUND",
                error_title="Join key field not found",
                user_message="One or more join key fields do not exist in the selected datasets.",
                diagnostics={
                    "missing_fields": missing,
                    "left_fields": [str(col) for col in left_obj.columns],
                    "right_fields": [str(col) for col in right_obj.columns],
                },
                next_actions=["Choose existing key fields from both datasets, then retry the attribute join."],
            ).to_json()

        try:
            right_attrs = right_obj.drop(columns=["geometry"], errors="ignore").copy()
            merged = left_obj.merge(right_attrs, how="left", left_on=left_key, right_on=right_key, suffixes=("", "_joined"))
            matched_rows = int(merged[right_key].notna().sum()) if right_key in merged.columns else 0

            if left_type == "vector":
                saved_name = manager.put_vector(output_name, gpd.GeoDataFrame(merged, geometry=left_obj.geometry, crs=getattr(left_obj, "crs", None)))
                artifact_type = "dataset"
            else:
                saved_name = manager.put_table(output_name, pd.DataFrame(merged))
                artifact_type = "dataset"
            record = manager.get(saved_name)
            manager.log_operation("属性连接", f"{left_name} <- {right_name} | {left_key}={right_key}", "analysis")
            return tool_result_ok(
                "join_attributes",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "row_count": int(len(merged)),
                    "path": str(record.path),
                    "left_type": left_type,
                    "matched_rows": matched_rows,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type=artifact_type,
                        title=saved_name,
                        description=f"Attribute join result from {left_name} and {right_name}.",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"Joined attributes from {right_name} to {left_name} into {saved_name}.",
                diagnostics={
                    "left_rows": int(len(left_obj)),
                    "right_rows": int(len(right_obj)),
                    "result_rows": int(len(merged)),
                    "matched_rows": matched_rows,
                    "left_key": left_key,
                    "right_key": right_key,
                },
                warnings=[] if matched_rows else ["No rows matched the selected join keys."],
                next_actions=["Inspect join match counts, then map, model, or export the joined dataset."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("join_attributes", inputs, exc)


    @tool
    def summarize_points_within_polygons(
        point_name: str,
        polygon_name: str,
        output_name: str,
        count_field: str = "point_count",
        numeric_field: str = "",
        stat: str = "mean",
    ) -> str:
        """统计面内点数量，并可对点属性做聚合统计。适合 POI、站点、样点等点位汇总到行政区或网格。"""
        inputs = {
            "point_name": point_name,
            "polygon_name": polygon_name,
            "output_name": output_name,
            "count_field": count_field,
            "numeric_field": numeric_field,
            "stat": stat,
        }
        allowed_stats = {"mean", "sum", "min", "max", "median"}
        if stat not in allowed_stats:
            return tool_result_error(
                "summarize_points_within_polygons",
                inputs=inputs,
                error_code="STAT_UNSUPPORTED",
                error_title="统计方式不支持",
                user_message=f"stat 必须是 {', '.join(sorted(allowed_stats))} 之一。",
                diagnostics={"allowed": sorted(allowed_stats), "received": stat},
                next_actions=["请选择一种受支持的统计方式后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, point_name))
        errors.extend(validate_dataset_exists(manager, polygon_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not str(count_field or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_FIELD_REQUIRED",
                    "error_title": "缺少输出字段",
                    "user_message": "请指定保存点数量的 count_field。",
                    "next_actions": ["提供 count_field，例如 point_count。"],
                    "diagnostics": {},
                }
            )
        if not errors:
            errors.extend(validate_vector_readable(manager, point_name))
            errors.extend(validate_vector_readable(manager, polygon_name))
            errors.extend(validate_crs(manager, point_name))
            errors.extend(validate_crs(manager, polygon_name))
            errors.extend(validate_geometry_type(manager, point_name, ["Point"]))
            errors.extend(validate_geometry_type(manager, polygon_name, ["Polygon", "MultiPolygon"]))
            if str(numeric_field or "").strip():
                errors.extend(validate_required_fields(manager, point_name, [numeric_field]))
                errors.extend(validate_numeric_fields(manager, point_name, [numeric_field]))
        if errors:
            return _tool_error_from_validation("summarize_points_within_polygons", inputs, errors)
        try:
            points = manager.get_vector(point_name)
            polygons = manager.get_vector(polygon_name)
            points, polygons = _align_crs(points, polygons)
            joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
            grouped_count = joined.groupby("index_right").size()

            result = polygons.copy()
            result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)
            fields_added = [count_field]
            if numeric_field:
                grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
                out_field = f"{numeric_field}_{stat}"
                result[out_field] = result.index.to_series().map(grouped_values)
                fields_added.append(out_field)

            saved_name = manager.put_vector(output_name, result)
            record = manager.get(saved_name)
            manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "summarize_points_within_polygons",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(result)),
                    "path": str(record.path),
                    "fields_added": fields_added,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{point_name} summarized within {polygon_name}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已将 {point_name} 汇总到 {polygon_name}，输出 {saved_name}，新增字段 {', '.join(fields_added)}。",
                diagnostics={
                    "point_count": int(len(points)),
                    "polygon_count": int(len(polygons)),
                    "matched_points": int(len(joined)),
                    "stat": stat,
                    "crs": str(polygons.crs),
                },
                next_actions=["可继续对统计字段制图、排序检查异常区域，或导出结果。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("summarize_points_within_polygons", inputs, exc)
        points = manager.get_vector(point_name)
        polygons = manager.get_vector(polygon_name)
        points, polygons = _align_crs(points, polygons)
        joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
        grouped_count = joined.groupby("index_right").size()

        result = polygons.copy()
        result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)

        extra_msg = ""
        if numeric_field:
            if numeric_field not in joined.columns:
                raise ValueError(f"点图层中未找到字段 {numeric_field}。可用字段: {list(joined.columns)}")
            allowed = {"mean", "sum", "min", "max", "median"}
            if stat not in allowed:
                raise ValueError(f"stat 必须是 {sorted(allowed)} 之一")
            grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
            out_field = f"{numeric_field}_{stat}"
            result[out_field] = result.index.to_series().map(grouped_values)
            extra_msg = f"，并计算了 {numeric_field} 的 {stat}: 字段 {out_field}"

        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
        return f"面内点统计完成，结果: {saved_name}，计数字段 {count_field}{extra_msg}，保存路径 {manager.get(saved_name).path}"

        inputs = {"point_name": point_name, "raster_name": raster_name, "output_name": output_name, "field_name": field_name, "band": band}
        errors = []
        errors.extend(validate_dataset_exists(manager, point_name))
        errors.extend(validate_dataset_exists(manager, raster_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, point_name))
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_crs(manager, point_name))
            errors.extend(validate_geometry_type(manager, point_name, ["Point"]))
        if not str(field_name or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_FIELD_REQUIRED",
                    "error_title": "缺少输出字段",
                    "user_message": "请指定用于保存栅格值的输出字段名。",
                    "next_actions": ["提供 field_name，例如 raster_val。"],
                    "diagnostics": {},
                }
            )
        if errors:
            return _tool_error_from_validation("extract_raster_values_to_points", inputs, errors)
        try:
            points = manager.get_vector(point_name)
            raster_path = manager.get_raster_path(raster_name)

            with rasterio.open(raster_path) as src:
                if band < 1 or band > src.count:
                    return tool_result_error(
                        "extract_raster_values_to_points",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="栅格波段不存在",
                        user_message=f"请求的波段 {band} 不在栅格波段范围内。",
                        diagnostics={"band": band, "band_count": src.count},
                        next_actions=["选择 1 到栅格波段数之间的 band。"],
                    ).to_json()
                pts = points.copy()
                if pts.crs and src.crs and pts.crs != src.crs:
                    pts = pts.to_crs(src.crs)
                coords = [(geom.x, geom.y) for geom in pts.geometry if geom is not None]
                values = [val[0] if len(val) else None for val in src.sample(coords, indexes=band)]
                result = points.copy()
                result[field_name] = values

            saved_name = manager.put_vector(output_name, result)
            output_path = manager.get(saved_name).path
            manager.log_operation("栅格抽样到点", f"{raster_name} -> {point_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "extract_raster_values_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(result)), "field_name": field_name, "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} raster sampled points",
                        description=f"点图层 {point_name} 提取栅格 {raster_name} 后的结果。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"栅格值提取完成，结果数据集 {saved_name}，字段 {field_name}。",
                diagnostics={"sample_count": int(len(values)), "band": int(band), "raster": raster_name},
                next_actions=["检查提取字段的缺失值和异常值。", "可继续用于建模或专题制图。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("extract_raster_values_to_points", inputs, exc)
        points = manager.get_vector(point_name)
        polygons = manager.get_vector(polygon_name)
        points, polygons = _align_crs(points, polygons)
        joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
        grouped_count = joined.groupby("index_right").size()

        result = polygons.copy()
        result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)

        extra_msg = ""
        if numeric_field:
            if numeric_field not in joined.columns:
                raise ValueError(f"点图层中未找到字段: {numeric_field}。可用字段: {list(joined.columns)}")
            allowed = {"mean", "sum", "min", "max", "median"}
            if stat not in allowed:
                raise ValueError(f"stat 必须是 {sorted(allowed)} 之一")
            grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
            out_field = f"{numeric_field}_{stat}"
            result[out_field] = result.index.to_series().map(grouped_values)
            extra_msg = f"，并计算了 {numeric_field} 的 {stat}: 字段 {out_field}"

        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
        return f"面内点统计完成，结果: {saved_name}，计数字段: {count_field}{extra_msg}，保存路径: {manager.get(saved_name).path}"


    return [
        vector_filter,
        vector_buffer,
        vector_clip_by_vector,
        vector_overlay,
        vector_dissolve,
        vector_spatial_join,
        reproject_vector,
        create_centroids,
        calculate_geometry_fields,
        join_attributes,
        summarize_points_within_polygons,
    ]
