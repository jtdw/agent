from __future__ import annotations

from typing import Any

from core.tools import map_helpers as _helpers

MAP_TOOL_NAMES = {
    'plot_dataset',
    'raster_histogram',
    'export_dataset',
    'generate_thesis_charts',
}

_LEGACY_DEPENDENCIES = (
    'Any',
    'ArtifactInfo',
    'GCP_METRIC_COLUMNS',
    'Path',
    'STANDARD_METRIC_COLUMNS',
    '_ACTIVE_FONT',
    '_artifact_safe_name',
    '_calc_metrics',
    '_coerce_numeric_frame',
    '_ensure_datetime',
    '_ensure_metric_predicted_column',
    '_find_dataset_with_columns',
    '_infer_metric_columns',
    '_infer_observed_column',
    '_parse_columns',
    '_prepare_dataframe',
    '_prepare_dataframe_with_geometry',
    '_resolve_existing_columns',
    '_safe_map_title',
    '_save_markdown_artifact',
    '_save_vector_map_plot',
    '_tool_error_from_validation',
    '_tool_internal_error',
    '_validate_columns',
    'contextlib',
    'io',
    'np',
    'os',
    'pd',
    'plt',
    'pyogrio',
    'raster_show',
    'rasterio',
    'shutil',
    'tool',
    'tool_result_error',
    'tool_result_ok',
    'uuid4',
    'validate_crs',
    'validate_dataset_exists',
    'validate_output_file_path',
    'validate_output_path',
    'validate_raster_readable',
    'validate_required_fields',
    'validate_vector_readable',
    'warnings',
    'zipfile',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)

def build_map_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    @tool
    def plot_dataset(dataset_name: str, column: str = "", title: str = "", output_name: str = "") -> str:
        """为矢量或栅格数据生成地图 PNG。矢量可选 column 进行专题制图。"""
        inputs = {"dataset_name": dataset_name, "column": column, "title": title, "output_name": output_name}
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.plot_dir, output_name, allowed_suffixes={".png"}))
        if errors:
            return _tool_error_from_validation("plot_dataset", inputs, errors)

        try:
            record = manager.get(dataset_name)
        except Exception as exc:
            return _tool_internal_error("plot_dataset", inputs, exc)

        if record.data_type == "table":
            return tool_result_error(
                "plot_dataset",
                inputs=inputs,
                error_code="UNSUPPORTED_DATASET_TYPE",
                error_title="表格不能直接制图",
                user_message="表格数据不能直接绘制为空间地图，需要先转换为点图层或选择已有矢量/栅格数据。",
                diagnostics={"dataset_type": record.data_type},
                next_actions=["先使用 table_to_points 将经纬度表转换为点图层。", "或选择一个矢量/栅格数据集制图。"],
            ).to_json()
        if record.data_type not in {"vector", "raster"}:
            return tool_result_error(
                "plot_dataset",
                inputs=inputs,
                error_code="UNSUPPORTED_DATASET_TYPE",
                error_title="数据类型不支持制图",
                user_message=f"当前数据类型 {record.data_type} 暂不支持直接制图。",
                diagnostics={"dataset_type": record.data_type},
                next_actions=["选择矢量或栅格数据集。"],
            ).to_json()

        errors = []
        if record.data_type == "vector":
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
            if str(column or "").strip():
                errors.extend(validate_required_fields(manager, dataset_name, [column]))
        else:
            errors.extend(validate_raster_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("plot_dataset", inputs, errors)

        try:
            record = manager.get(dataset_name)
            output_stem = output_name or f"{dataset_name}_map"
            if Path(output_stem).suffix.lower() == ".png":
                output_stem = Path(output_stem).stem
            output_path = manager.plot_dir / f"{output_stem}.png"
            fig, ax = plt.subplots(figsize=(9.6, 6.8))
            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#f8fafc")
            if record.data_type == "vector":
                plt.close(fig)
                gdf = manager.get_vector(dataset_name)
                _save_vector_map_plot(gdf, output_path, column=column, title=title or dataset_name)
            else:
                raster_path = manager.get_raster_path(dataset_name)
                with rasterio.open(raster_path) as src:
                    raster_show(src, ax=ax, cmap="viridis")
                ax.set_title(_safe_map_title(title or dataset_name), color="white", pad=12)
                ax.grid(alpha=0.15)
                ax.spines[["top", "right"]].set_visible(False)
                plt.tight_layout()
                fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
                plt.close(fig)

            manager.last_plot_path = str(output_path)
            manager.log_operation("生成地图", f"{dataset_name} -> {output_path.name}", "plot")
            font_msg = f"使用字体 {_ACTIVE_FONT}" if _ACTIVE_FONT else "未检测到可用中文字体，标题可能自动降级"
            return tool_result_ok(
                "plot_dataset",
                inputs=inputs,
                outputs={"path": str(output_path), "dataset_name": dataset_name, "column": column or ""},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"map_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="map",
                        title=title or f"{dataset_name} map",
                        description=f"数据集 {dataset_name} 的地图图件。",
                        quality_status="created",
                        preview_available=True,
                    )
                ],
                summary=f"地图已生成：{output_path}",
                diagnostics={"dataset_type": record.data_type, "font": font_msg, "crs": record.meta.get("crs") if isinstance(record.meta, dict) else None},
                next_actions=["查看图件空间分布，并结合字段含义解释异常区域。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("plot_dataset", inputs, exc)

        output_stem = output_name or f"{dataset_name}_map"
        output_path = manager.plot_dir / f"{output_stem}.png"

        fig, ax = plt.subplots(figsize=(9.6, 6.8))
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#f8fafc")

        if record.data_type == "vector":
            plt.close(fig)
            gdf = manager.get_vector(dataset_name)
            _save_vector_map_plot(gdf, output_path, column=column, title=title or dataset_name)
            font_msg = f"，使用字体: {_ACTIVE_FONT}" if _ACTIVE_FONT else "，未检测到可用中文字体，已自动降级为英文标题或静默告警"
            manager.last_plot_path = str(output_path)
            manager.log_operation("生成地图", f"{dataset_name} -> {output_path.name}", "plot")
            return f"地图已生成: {output_path}{font_msg}"
        elif record.data_type == "raster":
            raster_path = manager.get_raster_path(dataset_name)
            with rasterio.open(raster_path) as src:
                raster_show(src, ax=ax, cmap="viridis")
        elif record.data_type == "table":
            raise ValueError("表格数据不能直接制图，请先转为点图层。")
        else:
            raise ValueError(f"暂不支持绘制的数据类型: {record.data_type}")

        ax.set_title(_safe_map_title(title or dataset_name), color="white" if record.data_type == "raster" else "#e2e8f0", pad=12)
        ax.grid(alpha=0.15)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)

        font_msg = f"，使用字体: {_ACTIVE_FONT}" if _ACTIVE_FONT else "，未检测到可用中文字体，已自动降级为英文标题或静默告警"
        manager.last_plot_path = str(output_path)
        manager.log_operation("生成地图", f"{dataset_name} -> {output_path.name}", "plot")
        return f"地图已生成: {output_path}{font_msg}"


    @tool
    def raster_histogram(dataset_name: str, band: int = 1, output_name: str = "") -> str:
        """为栅格波段生成直方图 PNG，便于查看数值分布。"""
        inputs = {"dataset_name": dataset_name, "band": band, "output_name": output_name}
        output_stem = output_name or f"{dataset_name}_hist"
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.plot_dir, output_stem, allowed_suffixes={".png"}))
        if not errors:
            errors.extend(validate_raster_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("raster_histogram", inputs, errors)

        try:
            raster_path = manager.get_raster_path(dataset_name)
            output_path = manager.plot_dir / f"{Path(output_stem).stem}.png"
            with rasterio.open(raster_path) as src:
                if band < 1 or band > src.count:
                    return tool_result_error(
                        "raster_histogram",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="波段编号超出范围",
                        user_message=f"数据 {dataset_name} 只有 {src.count} 个波段，不能读取第 {band} 个波段。",
                        diagnostics={"band": band, "band_count": int(src.count)},
                        next_actions=["请选择 1 到波段总数之间的 band 参数后重试。"],
                    ).to_json()
                arr = src.read(band, masked=True)
                valid = arr.compressed()
                if valid.size == 0:
                    return tool_result_error(
                        "raster_histogram",
                        inputs=inputs,
                        error_code="RASTER_BAND_EMPTY",
                        error_title="波段没有有效像元",
                        user_message=f"{dataset_name} 的第 {band} 个波段没有有效像元，无法生成直方图。",
                        diagnostics={"band": band, "valid_count": 0},
                        next_actions=["检查 NoData 设置，或选择其他波段/数据集。"],
                    ).to_json()

            fig, ax = plt.subplots(figsize=(8.5, 5.5))
            ax.hist(valid, bins=30, color="#38bdf8", edgecolor="#0f172a")
            ax.set_title(_safe_map_title(f"{dataset_name} histogram"))
            ax.set_xlabel("Value")
            ax.set_ylabel("Frequency")
            ax.grid(alpha=0.2)
            plt.tight_layout()
            fig.savefig(output_path, dpi=220, bbox_inches="tight")
            plt.close(fig)
            manager.last_plot_path = str(output_path)
            manager.log_operation("栅格直方图", f"{dataset_name} band {band} -> {output_path.name}", "plot")
            return tool_result_ok(
                "raster_histogram",
                inputs=inputs,
                outputs={"path": str(output_path), "band": int(band), "valid_count": int(valid.size)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"plot:{output_path.name}",
                        path=str(output_path),
                        type="plot",
                        title=output_path.name,
                        description=f"Histogram for {dataset_name} band {band}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已生成 {dataset_name} 第 {band} 波段的直方图，共统计 {valid.size} 个有效像元。",
                diagnostics={
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": float(np.mean(valid)),
                    "valid_count": int(valid.size),
                },
                next_actions=["可继续查看直方图判断异常值、偏态分布或分级制图阈值。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_histogram", inputs, exc)
        raster_path = manager.get_raster_path(dataset_name)
        output_stem = output_name or f"{dataset_name}_hist"
        output_path = manager.plot_dir / f"{output_stem}.png"
        with rasterio.open(raster_path) as src:
            arr = src.read(band, masked=True)
            valid = arr.compressed()
            if valid.size == 0:
                raise ValueError("该波段没有有效像元，无法生成直方图。")
        fig, ax = plt.subplots(figsize=(8.5, 5.5))
        ax.hist(valid, bins=30, color="#38bdf8", edgecolor="#0f172a")
        ax.set_title(_safe_map_title(f"{dataset_name} histogram"))
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        ax.grid(alpha=0.2)
        plt.tight_layout()
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        manager.last_plot_path = str(output_path)
        manager.log_operation("栅格直方图", f"{dataset_name} band {band} -> {output_path.name}", "plot")
        return f"直方图已生成: {output_path}"


    @tool
    def export_dataset(dataset_name: str, output_path: str) -> str:
        """将已有结果导出到指定路径。矢量默认导出为 GeoJSON，表格导出为 CSV，栅格直接复制，文档导出为文本。"""
        inputs = {"dataset_name": dataset_name, "output_path": output_path}
        errors = validate_dataset_exists(manager, dataset_name)
        if not str(output_path or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_PATH_REQUIRED",
                    "error_title": "缺少导出路径",
                    "user_message": "请指定导出文件路径。",
                    "next_actions": ["提供 output_path，例如 results/output.csv。"],
                    "diagnostics": {},
                }
            )
        else:
            errors.extend(validate_output_file_path(manager.workdir, output_path))
        if errors:
            return _tool_error_from_validation("export_dataset", inputs, errors)
        try:
            record = manager.get(dataset_name)
            raw_target = Path(output_path)
            target = raw_target.resolve() if raw_target.is_absolute() else (manager.workdir / raw_target).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            export_details: dict[str, Any] = {}
            export_warnings: list[dict[str, Any]] = []

            if record.data_type == "vector":
                gdf = manager.get_vector(dataset_name)
                suffix = target.suffix.lower()
                if suffix == ".geojson":
                    gdf.to_file(target, driver="GeoJSON")
                elif suffix in {".shp", ".zip"}:
                    zip_target = target if suffix == ".zip" else target.with_suffix(".zip")
                    staging = target.parent / f".{target.stem}_shp_{uuid4().hex[:8]}"
                    staging.mkdir(parents=True, exist_ok=True)
                    export_warnings.append(
                        {
                            "code": "SHAPEFILE_ZIP_PACKAGE",
                            "message": "Shapefile exports are delivered as a zip package containing .shp/.shx/.dbf and available sidecar files.",
                            "next_actions": ["Use the zip file as the downloadable artifact; keep sidecar files together."],
                        }
                    )
                    long_field_names = [str(col) for col in gdf.columns if str(col) != "geometry" and len(str(col)) > 10]
                    if long_field_names:
                        export_warnings.append(
                            {
                                "code": "SHAPEFILE_FIELD_NAME_TRUNCATION",
                                "message": "ESRI Shapefile limits DBF field names to 10 characters; long names may be truncated by the writer.",
                                "fields": long_field_names,
                                "next_actions": ["Use GeoJSON when full field names must be preserved.", "Check exported DBF field names before downstream analysis."],
                            }
                        )
                    try:
                        shp_path = staging / f"{target.stem}.shp"
                        writer_stderr = io.StringIO()
                        previous_cpl_log = pyogrio.get_gdal_config_option("CPL_LOG")
                        pyogrio.set_gdal_config_options({"CPL_LOG": os.devnull})
                        with warnings.catch_warnings(record=True) as captured_warnings:
                            warnings.simplefilter("always")
                            try:
                                with contextlib.redirect_stderr(writer_stderr):
                                    gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="UTF-8")
                            finally:
                                pyogrio.set_gdal_config_options({"CPL_LOG": previous_cpl_log})
                        cpg_path = staging / f"{target.stem}.cpg"
                        if not cpg_path.exists():
                            cpg_path.write_text("UTF-8", encoding="ascii")
                        members = sorted(path for path in staging.glob(f"{target.stem}.*") if path.is_file())
                        with zipfile.ZipFile(zip_target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                            for member in members:
                                archive.write(member, arcname=member.name)
                        target = zip_target
                        export_details = {
                            "format": "shapefile_zip",
                            "requested_format": suffix,
                            "encoding": "UTF-8",
                            "members": [member.name for member in members],
                            "limitations": ["field_names_limited_to_10_characters", "multi_file_format_packaged_as_zip"],
                            "writer_warnings": [
                                *[str(item.message) for item in captured_warnings],
                                *[line.strip() for line in writer_stderr.getvalue().splitlines() if line.strip()],
                            ],
                        }
                    finally:
                        shutil.rmtree(staging, ignore_errors=True)
                else:
                    gdf.to_file(target)
            elif record.data_type == "table":
                df = manager.get_table(dataset_name)
                if target.suffix.lower() in {".xlsx", ".xls"}:
                    df.to_excel(target, index=False)
                else:
                    df.to_csv(target, index=False, encoding="utf-8-sig")
            elif record.data_type == "raster":
                source = manager.get_raster_path(dataset_name)
                shutil.copy2(source, target)
            elif record.data_type == "document":
                target.write_text(manager.get_document_text(dataset_name), encoding="utf-8")
            else:
                return tool_result_error(
                    "export_dataset",
                    inputs=inputs,
                    error_code="UNSUPPORTED_DATASET_TYPE",
                    error_title="数据类型不支持导出",
                    user_message=f"当前数据类型 {record.data_type} 暂不支持导出。",
                    diagnostics={"dataset_type": record.data_type},
                    next_actions=["请选择表格、矢量、栅格或文档数据集。"],
                ).to_json()

            manager.log_operation("导出结果", f"{dataset_name} -> {target}", "export")
            return tool_result_ok(
                "export_dataset",
                inputs=inputs,
                outputs={"path": str(target), "dataset_name": dataset_name, "dataset_type": record.data_type, **export_details},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"file:{target.name}",
                        path=str(target),
                        type="file",
                        title=target.name,
                        description=f"Exported {record.data_type} dataset {dataset_name}",
                        quality_status="ok",
                        preview_available=target.suffix.lower() in {".csv", ".txt", ".json", ".geojson"},
                    )
                ],
                summary=f"已导出 {dataset_name} 到 {target}。",
                diagnostics={
                    "dataset_type": record.data_type,
                    "path": str(target),
                    "bytes": int(target.stat().st_size) if target.exists() else 0,
                    "shapefile_encoding": export_details.get("encoding"),
                    "shapefile_limitations": export_details.get("limitations", []),
                    "shapefile_members": export_details.get("members", []),
                },
                warnings=export_warnings,
                next_actions=["可下载或在外部 GIS/表格软件中打开导出文件。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("export_dataset", inputs, exc)
        record = manager.get(dataset_name)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if record.data_type == "vector":
            gdf = manager.get_vector(dataset_name)
            driver = "GeoJSON" if target.suffix.lower() == ".geojson" else None
            if driver:
                gdf.to_file(target, driver=driver)
            else:
                gdf.to_file(target)
        elif record.data_type == "table":
            df = manager.get_table(dataset_name)
            if target.suffix.lower() in {".xlsx", ".xls"}:
                df.to_excel(target, index=False)
            else:
                df.to_csv(target, index=False, encoding="utf-8-sig")
        elif record.data_type == "raster":
            source = manager.get_raster_path(dataset_name)
            shutil.copy2(source, target)
        elif record.data_type == "document":
            target.write_text(manager.get_document_text(dataset_name), encoding="utf-8")
        else:
            raise ValueError(f"暂不支持导出的数据类型: {record.data_type}")

        manager.log_operation("导出结果", f"{dataset_name} -> {target}", "export")
        return f"导出完成: {target}"


    @tool
    def generate_thesis_charts(
        dataset_name: str,
        chart_type: str,
        output_prefix: str,
        x_col: str = "",
        y_cols: str = "",
        observed_col: str = "",
        group_col: str = "",
        metrics_cols: str = "R,RMSE,ubRMSE,NSE",
        title: str = "",
        top_n: int = 12,
    ) -> str:
        """自动生成适合论文使用的对比图、精度图、观测-预测散点图、BTCH 权重图和特征重要性图，并附带图注草稿。"""
        dataset_used = dataset_name
        df = _prepare_dataframe(dataset_used, manager).copy()
        chart_key = chart_type.strip().lower()
        files: list[str] = []
        captions: list[str] = []
        requested_metrics = _parse_columns(metrics_cols) if metrics_cols.strip() else []
        metrics_list, metric_family = _infer_metric_columns(df, requested=requested_metrics)
        if not metrics_list:
            fallback_requested = requested_metrics or STANDARD_METRIC_COLUMNS
            metrics_list = [col for col in fallback_requested if col in df.columns]

        def _switch_dataset_for_columns(required_cols: list[str]) -> None:
            nonlocal df, dataset_used, metrics_list, metric_family
            required = [str(col).strip() for col in required_cols if str(col).strip()]
            if not required:
                return
            missing = [col for col in required if col not in df.columns]
            if not missing:
                return
            alt_dataset = _find_dataset_with_columns(manager, required, current_dataset=dataset_used)
            if not alt_dataset:
                return
            dataset_used = alt_dataset
            df = _prepare_dataframe(dataset_used, manager).copy()
            metrics_list, metric_family = _infer_metric_columns(df, requested=requested_metrics)
            if not metrics_list:
                fallback_requested = requested_metrics or STANDARD_METRIC_COLUMNS
                metrics_list = [col for col in fallback_requested if col in df.columns]

        def _resolved_scatter_fields() -> tuple[str, list[str]]:
            requested = _parse_columns(y_cols)
            if observed_col.strip():
                requested.append(observed_col.strip())
            _switch_dataset_for_columns(requested)
            cols = _resolve_existing_columns(df, _parse_columns(y_cols))
            obs = _infer_observed_column(df, explicit_observed=observed_col, predicted_cols=cols)
            return obs, cols

        def _save_current(fig, suffix: str) -> str:
            path = manager.plot_dir / f"{_artifact_safe_name(output_prefix)}_{suffix}.png"
            fig.savefig(path, dpi=260, bbox_inches="tight")
            plt.close(fig)
            manager.last_plot_path = str(path)
            files.append(str(path))
            return str(path)

        def _render_time_series() -> None:
            cols = _parse_columns(y_cols)
            x_name = x_col or "date"
            _switch_dataset_for_columns([x_name, *cols])
            _validate_columns(df, cols)
            series = _ensure_datetime(df, x_name)
            work = df.copy()
            work[x_name] = series
            for col in cols:
                work[col] = pd.to_numeric(work[col], errors="coerce")
            grouped = work.groupby(x_name, dropna=False)[cols].mean().reset_index().sort_values(x_name)
            fig, ax = plt.subplots(figsize=(10, 6))
            for col in cols:
                ax.plot(grouped[x_name], grouped[col], linewidth=1.8, label=col)
            ax.set_title(_safe_map_title(title or f"{dataset_name} time series"))
            ax.set_xlabel(x_name)
            ax.set_ylabel("Value")
            ax.grid(alpha=0.25)
            ax.legend()
            _save_current(fig, "time_series")
            captions.append(f"图：{dataset_name} 中 {', '.join(cols)} 的时间序列对比。图中展示各变量在研究期内的平均时序变化，可用于论文中的时间维度比较分析。")

        def _render_metric_bar() -> None:
            work = _ensure_metric_predicted_column(df, dataset_name=dataset_name)
            local_metrics, local_family = _infer_metric_columns(work, requested=metrics_list)
            needed = ["predicted", *local_metrics]
            _validate_columns(work, needed)
            if group_col and group_col in work.columns:
                work[group_col] = work[group_col].astype(str)
                group_values = list(work[group_col].dropna().astype(str).unique())
                if group_values:
                    work = work[work[group_col].astype(str) == group_values[0]].copy()
            lower_is_better = {"RMSE", "UBRMSE", "BIAS", "MAE", "MPIW", "NMPIW", "QCP", "IS"}
            for metric in local_metrics:
                fig, ax = plt.subplots(figsize=(9.5, 5.8))
                plot_df = work[["predicted", metric]].copy().dropna().sort_values(metric, ascending=(metric.upper() in lower_is_better))
                ax.bar(plot_df["predicted"].astype(str), plot_df[metric])
                ax.set_title(_safe_map_title(title or f"{metric} comparison"))
                ax.set_xlabel("Model / Product")
                ax.set_ylabel(metric)
                ax.tick_params(axis="x", rotation=30)
                ax.grid(alpha=0.2, axis="y")
                _save_current(fig, f"metric_{metric.lower()}")
                if local_family == 'gcp':
                    captions.append(f"图：不同产品/模型的 {metric} 区间预测指标对比。该图用于比较 GCP 不确定性分析中的覆盖率、区间宽度或区间评分表现。")
                else:
                    captions.append(f"图：不同产品/模型的 {metric} 对比。该图用于比较 {metric} 指标上的优劣，可直接用于总体精度分析部分。")

        def _render_obs_pred_scatter() -> None:
            obs_col, cols = _resolved_scatter_fields()
            _validate_columns(df, [obs_col, *cols])
            work = _coerce_numeric_frame(df, [obs_col, *cols])
            for col in cols:
                paired = work[[obs_col, col]].dropna()
                if paired.empty:
                    continue
                fig, ax = plt.subplots(figsize=(6.6, 6.2))
                ax.scatter(paired[obs_col], paired[col], alpha=0.65, s=16)
                min_v = float(np.nanmin([paired[obs_col].min(), paired[col].min()]))
                max_v = float(np.nanmax([paired[obs_col].max(), paired[col].max()]))
                ax.plot([min_v, max_v], [min_v, max_v], linestyle="--", linewidth=1.2)
                metric = _calc_metrics(paired[obs_col], paired[col])
                ax.set_title(_safe_map_title(title or f"{col} vs {obs_col}"))
                ax.set_xlabel(obs_col)
                ax.set_ylabel(col)
                ax.grid(alpha=0.2)
                ax.text(0.03, 0.97, f"R={metric['R']:.3f}\nRMSE={metric['RMSE']:.3f}", transform=ax.transAxes, va="top")
                _save_current(fig, f"scatter_{_artifact_safe_name(col)}")
                captions.append(f"图：{col} 与 {obs_col} 的散点对比及 1:1 参考线。该图可用于说明模型/产品对观测值的一致性与离散程度。")

        def _render_feature_importance() -> None:
            feature_col = x_col or "feature"
            value_col = _parse_columns(y_cols)[0] if y_cols.strip() else "importance"
            _switch_dataset_for_columns([feature_col, value_col])
            _validate_columns(df, [feature_col, value_col])
            work = df[[feature_col, value_col]].copy().dropna().sort_values(value_col, ascending=False).head(top_n)
            fig, ax = plt.subplots(figsize=(9.5, 5.8))
            ax.barh(work[feature_col].astype(str)[::-1], work[value_col].astype(float)[::-1])
            ax.set_title(_safe_map_title(title or "Feature importance"))
            ax.set_xlabel(value_col)
            ax.set_ylabel(feature_col)
            ax.grid(alpha=0.2, axis="x")
            _save_current(fig, "feature_importance")
            captions.append("图：模型特征重要性排序。该图用于识别对融合结果贡献较高的变量，可用于解释 RF/XGBoost 模型的主要驱动因子。")

        def _render_btch_weights() -> None:
            _validate_columns(df, ["window", "product", "weight"])
            work = df.copy()
            work["window"] = work["window"].astype(str)
            work["weight"] = pd.to_numeric(work["weight"], errors="coerce")
            order = sorted(work["window"].dropna().unique().tolist())
            fig, ax = plt.subplots(figsize=(10, 6))
            for product, sub in work.groupby("product", dropna=False):
                sub = sub.sort_values("window", key=lambda s: s.map({v: i for i, v in enumerate(order)}))
                ax.plot(sub["window"], sub["weight"], marker="o", linewidth=1.6, label=str(product))
            ax.set_title(_safe_map_title(title or "BTCH weight dynamics"))
            ax.set_xlabel("Window")
            ax.set_ylabel("Weight")
            ax.tick_params(axis="x", rotation=30)
            ax.grid(alpha=0.25)
            ax.legend()
            _save_current(fig, "btch_weights")
            captions.append("图：BTCH 融合中各产品权重随时间窗口的变化。该图可用于讨论不同产品在不同时段的相对可信度及其季节性特征。")

        def _pick_spatial_column(preferred_mode: str = "auto") -> str:
            available_df = _prepare_dataframe(dataset_used, manager).copy()
            candidates: list[str] = []
            if y_cols.strip():
                try:
                    candidates.extend(_resolve_existing_columns(available_df, _parse_columns(y_cols)))
                except Exception:
                    pass
            if x_col.strip() and x_col in available_df.columns:
                candidates.append(x_col)

            mode_order = []
            if preferred_mode == "residual":
                mode_order = ["_residual", "residual", "_gcp_radius", "_gcp_width", "_gcp_upper", "_gcp_lower"]
            elif preferred_mode == "prediction":
                mode_order = ["_xgb", "_rf", "_btch", "_lstm", "prediction", "_spatial_cv"]
            else:
                mode_order = ["_residual", "_gcp_radius", "_gcp_width", "_xgb", "_rf", "_btch", "_lstm", "prediction", "_spatial_cv"]

            for suffix in mode_order:
                for col in available_df.columns:
                    lowered = str(col).lower()
                    if suffix in lowered:
                        candidates.append(str(col))

            seen = set()
            ordered = []
            for col in candidates:
                if col not in seen:
                    seen.add(col)
                    ordered.append(col)

            for col in ordered:
                numeric = pd.to_numeric(available_df[col], errors="coerce")
                if numeric.notna().any():
                    return col
            raise ValueError("spatial_distribution 需要提供可映射的数值字段，或结果数据集中应包含 residual / prediction / gcp 等数值列。")

        def _render_spatial_distribution(preferred_mode: str = "auto") -> None:
            _, gdf = _prepare_dataframe_with_geometry(dataset_used, manager)
            if gdf is None:
                raise ValueError("spatial_distribution / residual_map 需要矢量数据集。")
            value_col = _pick_spatial_column(preferred_mode=preferred_mode)
            plot_gdf = gdf.copy()
            plot_gdf[value_col] = pd.to_numeric(plot_gdf[value_col], errors="coerce")
            plot_gdf = plot_gdf.dropna(subset=[value_col]).copy()
            if plot_gdf.empty:
                raise ValueError(f"字段 {value_col} 没有可用于空间分布图的有效数值。")
            path = manager.plot_dir / f"{_artifact_safe_name(output_prefix)}_{_artifact_safe_name(value_col)}_spatial_distribution.png"
            _save_vector_map_plot(plot_gdf, path, column=value_col, title=_safe_map_title(title or f"{dataset_used} spatial distribution of {value_col}"))
            manager.last_plot_path = str(path)
            files.append(str(path))
            captions.append(f"图：{value_col} 的空间分布图。该图用于展示预测值、残差或不确定性指标在空间上的异质性，可直接用于论文中的空间格局分析。")

        def _render_group_box() -> None:
            cols = _parse_columns(y_cols)
            _switch_dataset_for_columns([group_col, *cols])
            _validate_columns(df, [group_col, *cols])
            work = df.copy()
            work[group_col] = work[group_col].astype(str)
            for col in cols:
                plot_df = work[[group_col, col]].copy().dropna()
                groups = [sub[col].astype(float).tolist() for _, sub in plot_df.groupby(group_col)]
                labels = [str(k) for k, _ in plot_df.groupby(group_col)]
                fig, ax = plt.subplots(figsize=(9.5, 5.8))
                ax.boxplot(groups, labels=labels, showfliers=False)
                ax.set_title(_safe_map_title(title or f"{col} by {group_col}"))
                ax.set_xlabel(group_col)
                ax.set_ylabel(col)
                ax.tick_params(axis="x", rotation=25)
                ax.grid(alpha=0.2, axis="y")
                _save_current(fig, f"box_{_artifact_safe_name(col)}")
                captions.append(f"图：{col} 在不同 {group_col} 分组下的箱线图。该图适合用于空间分区或地类分组差异分析。")

        if chart_key == "time_series":
            _render_time_series()
        elif chart_key == "metric_bar":
            _render_metric_bar()
        elif chart_key == "obs_pred_scatter":
            _render_obs_pred_scatter()
        elif chart_key == "feature_importance":
            _render_feature_importance()
        elif chart_key == "btch_weights":
            _render_btch_weights()
        elif chart_key == "group_box":
            if not group_col:
                raise ValueError("group_box 需要提供 group_col。")
            _render_group_box()
        elif chart_key in {"spatial_distribution", "spatial_map", "residual_map", "residual_spatial", "prediction_map"}:
            preferred_mode = "auto"
            if chart_key in {"residual_map", "residual_spatial"}:
                preferred_mode = "residual"
            elif chart_key == "prediction_map":
                preferred_mode = "prediction"
            _render_spatial_distribution(preferred_mode=preferred_mode)
        elif chart_key == "auto_pack":
            if y_cols.strip():
                try:
                    _resolved_scatter_fields()
                    _render_obs_pred_scatter()
                    if x_col:
                        _render_time_series()
                except Exception:
                    pass
            metric_like_cols = set(STANDARD_METRIC_COLUMNS + GCP_METRIC_COLUMNS)
            if not files and len(metric_like_cols.intersection(set(df.columns))) >= 2:
                _render_metric_bar()
            elif not files and {"feature", "importance"}.issubset(df.columns):
                _render_feature_importance()
            elif {"window", "product", "weight"}.issubset(df.columns):
                _render_btch_weights()
            else:
                try:
                    _, gdf = _prepare_dataframe_with_geometry(dataset_used, manager)
                except Exception:
                    gdf = None
                if gdf is not None:
                    _render_spatial_distribution(preferred_mode="auto")
                else:
                    raise ValueError("auto_pack 未能从当前表结构推断图表类型，请显式指定 chart_type。")
        else:
            raise ValueError("chart_type 目前支持 time_series、metric_bar、obs_pred_scatter、feature_importance、btch_weights、group_box、spatial_distribution、spatial_map、residual_map、prediction_map、auto_pack。")

        if not files:
            raise ValueError("没有生成任何图件，请检查输入字段和数据有效性。")

        caption_text = "# 论文图表草稿\n\n" + "\n\n".join(f"{idx + 1}. {cap}" for idx, cap in enumerate(captions))
        caption_path = _save_markdown_artifact(manager, f"{output_prefix}_figure_notes", caption_text)
        manager.log_operation("论文图表生成", f"{dataset_used} -> {len(files)} files", "plot")
        return f"论文图表生成完成，共 {len(files)} 个 PNG。图件: {files}。图注草稿: {caption_path}"


    return [
        plot_dataset,
        raster_histogram,
        export_dataset,
        generate_thesis_charts,
    ]
