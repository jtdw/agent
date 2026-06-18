from __future__ import annotations

from typing import Any

from core.tools import ml_helpers as _helpers

ML_TOOL_NAMES = {
    'generic_xgboost_workflow',
    'evaluate_prediction_accuracy',
    'geographical_conformal_prediction',
    'btch_fusion_model',
    'train_rf_fusion_model',
    'train_xgboost_fusion_model',
    'train_lstm_fusion_model',
    'generate_model_comparison_summary',
    'run_database_training_pipeline',
    'explain_database_training_pipeline',
}

_LEGACY_DEPENDENCIES = (
    'Any',
    'ArtifactInfo',
    'DataLoader',
    'GroupKFold',
    'Path',
    'Pipeline',
    'RandomForestRegressor',
    'SimpleImputer',
    'TensorDataset',
    '_FusionLSTM',
    '_append_spatial_coordinates',
    '_artifact_safe_name',
    '_auto_bandwidth',
    '_build_lstm_sequences',
    '_build_mask_from_query',
    '_build_xgb_pipeline',
    '_calc_global_moran_i',
    '_calc_interval_metrics',
    '_calc_metrics',
    '_coerce_numeric_frame',
    '_conformal_quantile_level',
    '_ensure_datetime',
    '_estimate_btch_weights',
    '_extract_metric_highlights',
    '_json',
    '_kernel_weights',
    '_make_pipeline_run_id',
    '_make_spatial_blocks',
    '_metric_row_with_label',
    '_parse_columns',
    '_pipeline_steps_markdown',
    '_prepare_dataframe',
    '_prepare_dataframe_with_geometry',
    '_resolve_existing_columns',
    '_resolve_spatial_coordinates',
    '_save_json_artifact',
    '_save_markdown_artifact',
    '_save_vector_map_plot',
    '_split_train_test_by_date',
    '_summarize_train_test_metrics',
    '_tool_error_from_validation',
    '_tool_internal_error',
    '_validate_columns',
    '_weighted_quantile',
    '_weighted_row_sum',
    '_window_labels',
    'first_error',
    'generate_model_result_id',
    'joblib',
    'mask',
    'merge_next_actions',
    'nn',
    'np',
    'parse_tool_result',
    'pd',
    're',
    'tool',
    'tool_result_error',
    'tool_result_ok',
    'torch',
    'uuid4',
    'validate_crs',
    'validate_dataset_exists',
    'validate_geometry_type',
    'validate_model_target',
    'validate_numeric_fields',
    'validate_output_path',
    'validate_required_fields',
    'validation_diagnostics',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)

def build_ml_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    from core.tools.table_tools import build_table_tools
    from core.tools.map_tools import build_map_tools
    from core.tools.document_tools import build_document_tools

    _aux_tools = {tool.name: tool for tool in [*build_table_tools(manager), *build_map_tools(manager), *build_document_tools(manager)]}
    profile_missing_values = _aux_tools.get("profile_missing_values")
    build_time_features = _aux_tools.get("build_time_features")
    generate_thesis_charts = _aux_tools.get("generate_thesis_charts")
    generate_stage_report = _aux_tools.get("generate_stage_report")

    @tool
    def generic_xgboost_workflow(
        dataset_name: str = "",
        target_col: str = "",
        feature_cols: str = "",
        output_name: str = "",
        mode: str = "auto",
        task_type: str = "auto",
        raster_names: str = "",
        target_raster_name: str = "",
        sample_dataset_name: str = "",
        x_col: str = "",
        y_col: str = "",
        date_col: str = "",
        group_col: str = "",
        split_method: str = "auto",
        test_size: float = 0.2,
        random_state: int = 42,
        max_training_samples: int = 200000,
        max_prediction_pixels: int = 5000000,
        raster_resampling: str = "bilinear",
        categorical_strategy: str = "onehot",
    ) -> str:
        """Run generic XGBoost regression/classification for table, vector, sample+raster, or raster stack data."""
        from core.ml.generic_xgboost import run_generic_xgboost_workflow

        result = run_generic_xgboost_workflow(
            manager,
            dataset_name=dataset_name,
            target_col=target_col,
            feature_cols=feature_cols,
            output_name=output_name,
            mode=mode,
            task_type=task_type,
            raster_names=raster_names,
            target_raster_name=target_raster_name,
            sample_dataset_name=sample_dataset_name,
            x_col=x_col,
            y_col=y_col,
            date_col=date_col,
            group_col=group_col,
            split_method=split_method,
            test_size=test_size,
            random_state=random_state,
            max_training_samples=max_training_samples,
            max_prediction_pixels=max_prediction_pixels,
            raster_resampling=raster_resampling,
            categorical_strategy=categorical_strategy,
        )
        return _json(result.to_dict())


    @tool
    def evaluate_prediction_accuracy(
        dataset_name: str,
        observed_col: str,
        predicted_cols: str,
        output_name: str = "",
        group_col: str = "",
    ) -> str:
        """对观测列与一个或多个预测列计算 R、RMSE、ubRMSE、Bias、NSE、MAE，适合土壤水分产品和融合模型比较。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        pred_cols = _parse_columns(predicted_cols) if str(predicted_cols or "").strip() else []
        _validate_columns(df, [observed_col, *pred_cols])
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")

        rows: list[dict[str, object]] = []
        if group_col:
            for group_value, sub_df in df.groupby(group_col, dropna=False):
                for pred_col in pred_cols:
                    metrics = _calc_metrics(sub_df[observed_col], sub_df[pred_col])
                    rows.append({"group": group_value, "observed": observed_col, "predicted": pred_col, **metrics})
        else:
            for pred_col in pred_cols:
                metrics = _calc_metrics(df[observed_col], df[pred_col])
                rows.append({"observed": observed_col, "predicted": pred_col, **metrics})

        result_df = pd.DataFrame(rows)
        manager.log_operation("精度评价", f"{dataset_name} | {observed_col} vs {pred_cols}", "analysis")
        if output_name:
            saved_name = manager.put_table(output_name, result_df)
            return f"精度评价完成，结果表: {saved_name}，保存路径: {manager.get(saved_name).path}"
        return _json(result_df.to_dict(orient="records"))


    @tool
    def geographical_conformal_prediction(
        calibration_dataset: str,
        observed_col: str,
        predicted_cols: str,
        output_name: str,
        target_dataset_name: str = "",
        lon_col: str = "",
        lat_col: str = "",
        date_col: str = "",
        calibration_filter: str = "",
        target_filter: str = "",
        calibration_ratio: float = 0.3,
        calibration_selection: str = "latest",
        alpha: float = 0.1,
        bandwidth: float = 0.0,
        kernel: str = "gaussian",
        bin_count: int = 5,
    ) -> str:
        """对一个或多个模型预测结果执行地理共形预测（GCP），输出位置相关预测区间、覆盖率和区间宽度等不确定性指标；若缺少空间坐标则自动退化为全局 split conformal。"""
        inputs = {
            "calibration_dataset": calibration_dataset,
            "observed_col": observed_col,
            "predicted_cols": predicted_cols,
            "output_name": output_name,
            "target_dataset_name": target_dataset_name,
            "lon_col": lon_col,
            "lat_col": lat_col,
            "date_col": date_col,
            "alpha": alpha,
            "calibration_ratio": calibration_ratio,
        }
        pred_cols = _parse_columns(predicted_cols)
        validation_errors: list[dict[str, Any]] = []
        validation_errors.extend(validate_dataset_exists(manager, calibration_dataset))
        if str(target_dataset_name or "").strip():
            validation_errors.extend(validate_dataset_exists(manager, target_dataset_name))
        validation_errors.extend(validate_model_target(manager, calibration_dataset, observed_col))
        validation_errors.extend(validate_required_fields(manager, calibration_dataset, pred_cols))
        validation_errors.extend(validate_numeric_fields(manager, calibration_dataset, pred_cols))
        target_name_for_validation = target_dataset_name.strip() or calibration_dataset
        if target_name_for_validation != calibration_dataset:
            validation_errors.extend(validate_required_fields(manager, target_name_for_validation, pred_cols))
            validation_errors.extend(validate_numeric_fields(manager, target_name_for_validation, pred_cols))
        validation_errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not pred_cols:
            validation_errors.append({
                "error_code": "PREDICTED_FIELDS_MISSING",
                "error_title": "Missing predicted fields",
                "user_message": "Please provide at least one prediction field for GCP.",
                "next_actions": ["Choose one or more model prediction columns, for example xgb_pred or rf_pred."],
                "diagnostics": {},
            })
        if not 0 < float(alpha) < 1:
            validation_errors.append({
                "error_code": "ALPHA_OUT_OF_RANGE",
                "error_title": "Invalid alpha",
                "user_message": "alpha must be between 0 and 1.",
                "next_actions": ["Use alpha=0.1 for a 90% prediction interval."],
                "diagnostics": {"alpha": alpha},
            })
        if not 0 < float(calibration_ratio) < 1:
            validation_errors.append({
                "error_code": "CALIBRATION_RATIO_OUT_OF_RANGE",
                "error_title": "Invalid calibration ratio",
                "user_message": "calibration_ratio must be between 0 and 1.",
                "next_actions": ["Use a value such as 0.3 when no explicit calibration filter is provided."],
                "diagnostics": {"calibration_ratio": calibration_ratio},
            })
        calibration_selection = (calibration_selection or "latest").strip().lower()
        if calibration_selection not in {"latest", "earliest", "random"}:
            validation_errors.append({
                "error_code": "CALIBRATION_SELECTION_UNSUPPORTED",
                "error_title": "Unsupported calibration selection",
                "user_message": "calibration_selection only supports latest, earliest, or random.",
                "next_actions": ["Use latest, earliest, or random."],
                "diagnostics": {"calibration_selection": calibration_selection},
            })
        if validation_errors:
            first = first_error(validation_errors) or {}
            return tool_result_error(
                "geographical_conformal_prediction",
                inputs=inputs,
                error_code=str(first.get("error_code") or "GCP_PRECONDITION_FAILED"),
                error_title=str(first.get("error_title") or "GCP precondition failed"),
                user_message=str(first.get("user_message") or "GCP inputs are incomplete or invalid."),
                diagnostics=validation_diagnostics(validation_errors),
                next_actions=merge_next_actions(validation_errors),
                technical_detail=str(first.get("technical_detail") or ""),
            ).to_json()

        cal_df = _prepare_dataframe(calibration_dataset, manager).copy()
        target_name = target_dataset_name.strip() or calibration_dataset
        target_df, target_gdf = _prepare_dataframe_with_geometry(target_name, manager)
        target_df = target_df.copy()

        _validate_columns(cal_df, [observed_col, *pred_cols])
        _validate_columns(target_df, pred_cols)
        if observed_col in target_df.columns:
            target_has_obs = True
        else:
            target_has_obs = False

        if date_col:
            if date_col in cal_df.columns:
                cal_df[date_col] = _ensure_datetime(cal_df, date_col)
            if date_col in target_df.columns:
                target_df[date_col] = _ensure_datetime(target_df, date_col)

        cal_coords, cal_coord_meta = _resolve_spatial_coordinates(calibration_dataset, cal_df, manager, lon_col=lon_col, lat_col=lat_col)
        target_coords, target_coord_meta = _resolve_spatial_coordinates(target_name, target_df, manager, lon_col=lon_col, lat_col=lat_col)
        spatial_ready = bool(
            cal_coords is not None and target_coords is not None and
            cal_coord_meta.get("spatial_ready") and target_coord_meta.get("spatial_ready")
        )

        cal_mask = pd.Series(True, index=cal_df.index)
        if calibration_filter.strip():
            cal_mask &= _build_mask_from_query(cal_df, calibration_filter, "calibration_filter")
        else:
            base_valid = cal_df[observed_col].notna()
            rng = np.random.default_rng(42)
            if date_col and date_col in cal_df.columns:
                ordered = cal_df.loc[base_valid].sort_values(date_col)
                take_n = max(20, int(len(ordered) * float(calibration_ratio)))
                take_n = min(len(ordered), take_n)
                if calibration_selection == "earliest":
                    chosen = ordered.index[:take_n]
                elif calibration_selection == "latest":
                    chosen = ordered.index[-take_n:]
                else:
                    chosen = rng.choice(ordered.index.to_numpy(), size=take_n, replace=False) if take_n else []
                cal_mask &= cal_df.index.isin(chosen)
            else:
                valid_index = cal_df.index[base_valid].to_numpy()
                take_n = max(20, int(len(valid_index) * float(calibration_ratio))) if len(valid_index) else 0
                take_n = min(len(valid_index), take_n)
                if calibration_selection == "earliest":
                    chosen = valid_index[:take_n]
                elif calibration_selection == "latest":
                    chosen = valid_index[-take_n:]
                else:
                    chosen = rng.choice(valid_index, size=take_n, replace=False) if take_n else []
                cal_mask &= cal_df.index.isin(chosen)

        if target_filter.strip():
            target_mask = _build_mask_from_query(target_df, target_filter, "target_filter")
        elif target_name == calibration_dataset:
            target_mask = ~cal_mask
        else:
            target_mask = pd.Series(True, index=target_df.index)

        if target_name == calibration_dataset and not bool(target_mask.any()):
            target_mask = pd.Series(True, index=target_df.index)

        result_df = target_df.copy()
        metrics_rows: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        bw_value = float(bandwidth) if float(bandwidth) > 0 else None

        for pred_col in pred_cols:
            cal_work = pd.DataFrame({
                "obs": pd.to_numeric(cal_df[observed_col], errors="coerce"),
                "pred": pd.to_numeric(cal_df[pred_col], errors="coerce"),
            }, index=cal_df.index)
            cal_work["score"] = np.abs(cal_work["obs"] - cal_work["pred"])
            if cal_coords is not None:
                cal_work = cal_work.join(cal_coords)
            cal_valid = cal_mask & cal_work["obs"].notna() & cal_work["pred"].notna()
            if spatial_ready:
                cal_valid &= cal_work[["__coord_x__", "__coord_y__"]].notna().all(axis=1)
            cal_use = cal_work.loc[cal_valid].copy()
            if len(cal_use) < 20:
                return tool_result_error(
                    "geographical_conformal_prediction",
                    inputs=inputs,
                    error_code="GCP_CALIBRATION_SAMPLE_TOO_SMALL",
                    error_title="Calibration sample too small",
                    user_message=f"{pred_col} has only {len(cal_use)} usable calibration samples; at least 20 are required.",
                    diagnostics={"predicted_col": pred_col, "usable_calibration_samples": int(len(cal_use))},
                    next_actions=["Use a larger calibration set.", "Relax filters or increase calibration_ratio.", "Check missing values in observed and predicted columns."],
                ).to_json()

            quantile_level = _conformal_quantile_level(len(cal_use), float(alpha))
            global_qhat = _weighted_quantile(cal_use["score"].to_numpy(dtype=float), quantile_level)

            target_work = pd.DataFrame({
                "pred": pd.to_numeric(target_df[pred_col], errors="coerce"),
            }, index=target_df.index)
            if target_has_obs:
                target_work["obs"] = pd.to_numeric(target_df[observed_col], errors="coerce")
            if target_coords is not None:
                target_work = target_work.join(target_coords)
            target_valid = target_mask & target_work["pred"].notna()
            if spatial_ready:
                target_valid &= target_work[["__coord_x__", "__coord_y__"]].notna().all(axis=1)
            if not bool(target_valid.any()):
                return tool_result_error(
                    "geographical_conformal_prediction",
                    inputs=inputs,
                    error_code="GCP_TARGET_SAMPLE_EMPTY",
                    error_title="No usable target samples",
                    user_message=f"{pred_col} has no usable target samples for GCP.",
                    diagnostics={"predicted_col": pred_col, "target_dataset": target_name},
                    next_actions=["Check missing values in prediction columns.", "Relax target_filter.", "Use a target dataset that contains model predictions."],
                ).to_json()

            radius_col = f"{pred_col}_gcp_radius"
            lower_col = f"{pred_col}_gcp_lower"
            upper_col = f"{pred_col}_gcp_upper"
            cover_col = f"{pred_col}_gcp_covered"
            result_df[radius_col] = np.nan
            result_df[lower_col] = np.nan
            result_df[upper_col] = np.nan
            if target_has_obs:
                result_df[cover_col] = np.nan

            target_index = target_df.index[target_valid]
            local_qhat = np.full(len(target_index), float(global_qhat), dtype=float)
            method_used = "split_conformal"

            if spatial_ready:
                cal_xy = cal_use[["__coord_x__", "__coord_y__"]].to_numpy(dtype=float)
                target_xy = target_work.loc[target_index, ["__coord_x__", "__coord_y__"]].to_numpy(dtype=float)
                bw_local = float(bw_value) if bw_value is not None else _auto_bandwidth(cal_xy)
                scores = cal_use["score"].to_numpy(dtype=float)
                for i, xy in enumerate(target_xy):
                    dist = np.sqrt(np.sum(np.square(cal_xy - xy), axis=1))
                    weights = _kernel_weights(dist, bw_local, kernel)
                    if np.sum(weights) > 0:
                        local_qhat[i] = _weighted_quantile(scores, quantile_level, sample_weight=weights)
                method_used = "gcp"
                if bw_value is None:
                    bw_value = bw_local

            pred_values = target_work.loc[target_index, "pred"].to_numpy(dtype=float)
            lower_values = pred_values - local_qhat
            upper_values = pred_values + local_qhat
            result_df.loc[target_index, radius_col] = local_qhat
            result_df.loc[target_index, lower_col] = lower_values
            result_df.loc[target_index, upper_col] = upper_values
            if target_has_obs:
                obs_values = target_work.loc[target_index, "obs"]
                covered = ((obs_values >= lower_values) & (obs_values <= upper_values)).astype(float)
                result_df.loc[target_index, cover_col] = covered.to_numpy(dtype=float)
                interval_metrics = _calc_interval_metrics(
                    obs=obs_values,
                    lower=pd.Series(lower_values, index=target_index),
                    upper=pd.Series(upper_values, index=target_index),
                    alpha=float(alpha),
                    pred_reference=target_work.loc[target_index, "pred"],
                    bin_count=int(bin_count),
                )
            else:
                interval_metrics = {"n": 0, "PICP": None, "MPIW": None, "NMPIW": None, "QCP": None, "IS": None}

            metrics_rows.append({
                "predicted": pred_col,
                "method": method_used,
                "nominal_coverage": float(1 - alpha),
                "alpha": float(alpha),
                "n_calibration": int(len(cal_use)),
                "n_target": int(target_valid.sum()),
                "global_qhat": float(global_qhat),
                "bandwidth": float(bw_value) if bw_value is not None else None,
                "kernel": kernel,
                "coord_source": cal_coord_meta.get("coord_source") if spatial_ready else "none",
                "projected_crs": cal_coord_meta.get("projected_crs") if spatial_ready else None,
                "calibration_dataset": calibration_dataset,
                "target_dataset": target_name,
                "calibration_filter": calibration_filter or None,
                "target_filter": target_filter or None,
                **interval_metrics,
            })
            summary_rows.append({
                "predicted": pred_col,
                "method": method_used,
                "global_qhat": float(global_qhat),
                "n_calibration": int(len(cal_use)),
                "n_target": int(target_valid.sum()),
                "interval_columns": {
                    "radius": radius_col,
                    "lower": lower_col,
                    "upper": upper_col,
                    "covered": cover_col if target_has_obs else None,
                },
            })

        metrics_df = pd.DataFrame(metrics_rows)
        metrics_name = manager.put_table(f"{output_name}_gcp_metrics", metrics_df)
        summary_path = _save_json_artifact(manager, f"{output_name}_gcp_summary", {
            "calibration_dataset": calibration_dataset,
            "target_dataset": target_name,
            "observed_col": observed_col,
            "predicted_cols": pred_cols,
            "date_col": date_col or None,
            "calibration_filter": calibration_filter or None,
            "target_filter": target_filter or None,
            "alpha": float(alpha),
            "calibration_selection": calibration_selection,
            "kernel": kernel,
            "bandwidth": float(bw_value) if bw_value is not None else None,
            "spatial_ready": bool(spatial_ready),
            "coordinate_meta": {
                "calibration": cal_coord_meta,
                "target": target_coord_meta,
            },
            "models": summary_rows,
        })

        if target_gdf is not None:
            result_gdf = target_gdf.copy()
            for col in result_df.columns:
                if col not in result_gdf.columns:
                    result_gdf[col] = result_df[col]
                else:
                    result_gdf[col] = result_df[col]
            saved_name = manager.put_vector(output_name, result_gdf, filename=f"{_artifact_safe_name(output_name)}.geojson")
        else:
            saved_name = manager.put_table(output_name, result_df)

        manager.log_operation("GCP 不确定性分析", f"{calibration_dataset} -> {saved_name}", "analysis")
        model_lines = []
        for row in metrics_rows:
            model_lines.append(
                f"- {row['predicted']}: 方法={row['method']}，PICP={row['PICP'] if row['PICP'] is not None else 'NA'}，MPIW={row['MPIW'] if row['MPIW'] is not None else 'NA'}"
            )
        task_id = f"geographical_conformal_prediction_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("GCP", output_name)
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} GCP intervals",
                description="GCP interval prediction result dataset.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"metrics_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} GCP metrics",
                description="GCP interval reliability metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(summary_path),
                type="summary",
                title=f"{output_name} GCP summary",
                description="GCP configuration and interval column summary.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        metrics_payload = metrics_rows[0] if len(metrics_rows) == 1 else {"models": metrics_rows}
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=calibration_dataset,
            model_name="GCP",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts],
            artifacts=artifact_dicts,
            metrics=metrics_payload,
            diagnostics={
                "calibration_dataset": calibration_dataset,
                "target_dataset": target_name,
                "observed_col": observed_col,
                "predicted_cols": pred_cols,
                "spatial_ready": bool(spatial_ready),
                "summary": summary_rows,
            },
        )
        return tool_result_ok(
            "geographical_conformal_prediction",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "metrics_dataset": metrics_name,
                "summary_path": str(summary_path),
                "interval_columns": summary_rows,
                "methods": sorted({str(row.get("method") or "") for row in metrics_rows}),
                "spatial_ready": bool(spatial_ready),
            },
            artifacts=artifacts,
            summary=(
                f"GCP uncertainty analysis completed. Result dataset: {saved_name}. "
                f"Metrics dataset: {metrics_name}. "
                f"Spatially adaptive: {'yes' if spatial_ready else 'no, used global split conformal'}."
            ),
            diagnostics={"metrics": metrics_rows, "summary": summary_rows},
            next_actions=["Explain PICP, MPIW, NMPIW, QCP and IS.", "Compare interval reliability with point prediction accuracy."],
        ).to_json()


    @tool
    def btch_fusion_model(
        dataset_name: str,
        product_cols: str,
        output_name: str,
        date_col: str = "",
        window_mode: str = "global",
        group_col: str = "",
        min_samples: int = 20,
    ) -> str:
        """基于多产品误差协方差拟合进行 BTCH 风格加权融合，适合多源土壤水分产品的无真值加权集成与权重分析。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        products = _parse_columns(product_cols)
        if len(products) < 3:
            raise ValueError("BTCH 融合至少需要 3 个产品列。")
        _validate_columns(df, products)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        df = _coerce_numeric_frame(df, products)

        global_weights: dict[Any, np.ndarray] = {}
        global_info: dict[Any, dict[str, Any]] = {}
        groups = [(None, df)] if not group_col else list(df.groupby(group_col, dropna=False))
        for group_value, sub_df in groups:
            complete = sub_df[products].dropna()
            if len(complete) < max(min_samples, len(products) + 2):
                raise ValueError(f"组 {group_value if group_col else 'all'} 的完整样本不足，无法进行 BTCH 融合。")
            estimate = _estimate_btch_weights(complete.to_numpy(dtype=float))
            global_weights[group_value] = estimate["weights"]
            global_info[group_value] = estimate

        if date_col:
            df["_btch_window"] = _window_labels(df, date_col, window_mode)
        else:
            df["_btch_window"] = "global"
            window_mode = "global"

        weights_rows: list[dict[str, Any]] = []
        fused_series = pd.Series(np.nan, index=df.index, dtype=float)
        if group_col:
            grouped_items = list(df.groupby([group_col, "_btch_window"], dropna=False))
        else:
            grouped_items = [(('all', window), sub_df) for window, sub_df in df.groupby("_btch_window", dropna=False)]

        for key, sub_df in grouped_items:
            group_value = key[0] if group_col else None
            window_value = key[1] if group_col else key[1]
            current_est = global_info[group_value]
            if window_mode != "global":
                complete = sub_df[products].dropna()
                if len(complete) >= max(min_samples, len(products) + 2):
                    try:
                        current_est = _estimate_btch_weights(complete.to_numpy(dtype=float))
                    except Exception:
                        current_est = global_info[group_value]
            weights = current_est["weights"]
            estimate_method = current_est["estimation_method"]
            samples = current_est["samples"]
            fused_series.loc[sub_df.index] = _weighted_row_sum(sub_df[products], weights)
            variances = current_est["variances"]
            for col, weight, variance in zip(products, weights, variances):
                weights_rows.append({
                    "group": group_value if group_col else "all",
                    "window": window_value,
                    "product": col,
                    "weight": float(weight),
                    "estimated_variance": float(variance),
                    "samples": int(samples),
                    "estimation_method": estimate_method,
                })

        result = df.drop(columns=["_btch_window"]).copy()
        pred_col = f"{output_name}_btch"
        result[pred_col] = fused_series
        saved_name = manager.put_table(output_name, result)
        weights_df = pd.DataFrame(weights_rows)
        weight_table_name = manager.put_table(f"{output_name}_btch_weights", weights_df)
        summary_path = _save_json_artifact(manager, f"{output_name}_btch_summary", {
            "dataset": dataset_name,
            "products": products,
            "prediction_column": pred_col,
            "window_mode": window_mode,
            "group_col": group_col or None,
            "global_weights": {str(k if k is not None else 'all'): {col: float(w) for col, w in zip(products, v)} for k, v in global_weights.items()},
        })
        manager.log_operation("BTCH 融合", f"{dataset_name} -> {saved_name}", "model")
        return (
            f"BTCH 融合完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"权重表: {weight_table_name}。\n"
            f"摘要文件: {summary_path}"
        )


    @tool
    def train_rf_fusion_model(
        dataset_name: str,
        target_col: str,
        feature_cols: str,
        output_name: str,
        date_col: str = "",
        split_date: str = "",
        n_estimators: int = 300,
        max_depth: int = 12,
        min_samples_leaf: int = 1,
        random_state: int = 42,
    ) -> str:
        """训练随机森林融合模型并输出预测结果、特征重要性和训练/测试精度，适合多源土壤水分回归融合。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "feature_cols": feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "split_date": split_date,
        }
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        features_for_validation: list[str] = []
        if not errors:
            errors.extend(validate_model_target(manager, dataset_name, target_col))
            try:
                features_for_validation = _parse_columns(feature_cols)
            except Exception as exc:
                errors.append(
                    {
                        "error_code": "FEATURE_FIELDS_MISSING",
                        "error_title": "缺少特征字段",
                        "user_message": "请指定用于随机森林建模的特征字段。",
                        "next_actions": ["从数值字段中选择一个或多个特征字段。", "多个字段可用逗号分隔。"],
                        "diagnostics": {"technical_detail": str(exc)},
                    }
                )
            if features_for_validation:
                errors.extend(validate_required_fields(manager, dataset_name, features_for_validation))
                errors.extend(validate_numeric_fields(manager, dataset_name, features_for_validation))
            if date_col:
                errors.extend(validate_required_fields(manager, dataset_name, [date_col]))
        if errors:
            return _tool_error_from_validation("train_rf_fusion_model", inputs, errors)

        try:
            df = _prepare_dataframe(dataset_name, manager).copy()
        except Exception as exc:
            return _tool_internal_error("train_rf_fusion_model", inputs, exc)
        features = _parse_columns(feature_cols)
        _validate_columns(df, [target_col, *features])
        df = _coerce_numeric_frame(df, [target_col, *features])

        valid_target = df[target_col].notna()
        if date_col and split_date:
            train_mask, test_mask = _split_train_test_by_date(df, date_col, split_date)
        else:
            train_mask = valid_target.copy()
            test_mask = ~train_mask

        fit_mask = valid_target & train_mask
        if int(fit_mask.sum()) < 20:
            return tool_result_error(
                "train_rf_fusion_model",
                inputs=inputs,
                error_code="INSUFFICIENT_TRAINING_SAMPLES",
                error_title="训练样本不足",
                user_message=f"RF 可用于训练的有效样本不足，当前仅 {int(fit_mask.sum())} 条。",
                diagnostics={"valid_training_samples": int(fit_mask.sum()), "minimum_required": 20},
                next_actions=["补充样本或减少缺失值。", "确认目标变量和特征字段是否选择正确。"],
            ).to_json()

        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("rf", RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=max_depth if max_depth > 0 else None,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                n_jobs=-1,
            )),
        ])
        model.fit(df.loc[fit_mask, features], df.loc[fit_mask, target_col])
        pred_col = f"{output_name}_rf"
        df[pred_col] = model.predict(df[features])

        metrics = _summarize_train_test_metrics(df, target_col, pred_col, train_mask & valid_target, test_mask & valid_target if date_col and split_date else None)
        importances = model.named_steps["rf"].feature_importances_
        importance_df = pd.DataFrame({"feature": features, "importance": importances}).sort_values("importance", ascending=False).reset_index(drop=True)

        saved_name = manager.put_table(output_name, df)
        importance_name = manager.put_table(f"{output_name}_rf_importance", importance_df)
        metrics_name = manager.put_table(f"{output_name}_rf_metrics", pd.DataFrame([{"scope": k, **v} for k, v in metrics.items()]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_rf_model.joblib"
        joblib.dump(model, model_path)
        task_id = f"train_rf_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("RF", output_name)
        rf_artifact_ids = {
            "dataset": f"dataset_{uuid4().hex[:10]}",
            "metrics": f"metrics_{uuid4().hex[:10]}",
            "importance": f"importance_{uuid4().hex[:10]}",
            "model": f"model_{uuid4().hex[:10]}",
        }
        artifacts = [
            ArtifactInfo(
                artifact_id=rf_artifact_ids["dataset"],
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} RF predictions",
                description="Random forest prediction result table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["metrics"],
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="Random forest accuracy metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["importance"],
                path=str(manager.get(importance_name).path),
                type="feature_importance",
                title=f"{importance_name} feature importance",
                description="Random forest feature importance table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["model"],
                path=str(model_path),
                type="model",
                title=f"{output_name} RF model",
                description="Trained random forest model file.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.log_operation("RF 融合训练", f"{dataset_name} -> {saved_name}", "model")
        summary = (
            f"RF 模型训练完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"特征重要性表: {importance_name}。\n"
            f"精度指标表: {metrics_name}。\n"
            f"模型文件: {model_path}。"
        )
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="RF",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=list(rf_artifact_ids.values()),
            artifacts=artifact_dicts,
            metrics=metrics.get("overall") if isinstance(metrics.get("overall"), dict) else metrics,
            diagnostics={"metrics": metrics, "features": features, "target_col": target_col},
        )
        return tool_result_ok(
            "train_rf_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "metrics_dataset": metrics_name,
                "importance_dataset": importance_name,
                "model_path": str(model_path),
            },
            artifacts=artifacts,
            summary=summary,
            diagnostics={"metrics": metrics, "features": features, "target_col": target_col},
            next_actions=["解释 RF 指标和特征重要性。", "检查残差或继续与 XGBoost 结果对比。"],
        ).to_json()
        meta_path = _save_json_artifact(manager, f"{output_name}_rf_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "features": features,
            "prediction_column": pred_col,
            "split_date": split_date or None,
            "params": {
                "n_estimators": int(n_estimators),
                "max_depth": int(max_depth),
                "min_samples_leaf": int(min_samples_leaf),
                "random_state": int(random_state),
            },
            "metrics": metrics,
        })
        manager.log_operation("RF 融合训练", f"{dataset_name} -> {saved_name}", "model")
        return (
            f"RF 融合模型训练完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"特征重要性表: {importance_name}。\n"
            f"精度指标表: {metrics_name}。\n"
            f"模型文件: {model_path}。\n"
            f"摘要文件: {meta_path}"
        )


    @tool
    def train_xgboost_fusion_model(
        dataset_name: str,
        target_col: str,
        feature_cols: str,
        output_name: str,
        date_col: str = "",
        split_date: str = "",
        n_estimators: int = 500,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        subsample: float = 0.9,
        colsample_bytree: float = 0.9,
        random_state: int = 42,
        spatial_validation: bool = True,
        spatial_block_count: int = 5,
        add_spatial_coordinates: bool = True,
        moran_k_neighbors: int = 8,
        moran_permutations: int = 199,
    ) -> str:
        """训练 XGBoost 回归模型。对点图层会自动保留 geometry、添加空间坐标特征、执行空间分块交叉验证、计算残差 Moran's I，并输出残差空间分布图。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "feature_cols": feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "split_date": split_date,
            "spatial_validation": spatial_validation,
        }
        errors = validate_dataset_exists(manager, dataset_name)
        features_for_validation: list[str] = []
        if not errors:
            errors.extend(validate_model_target(manager, dataset_name, target_col))
            try:
                features_for_validation = _parse_columns(feature_cols)
            except Exception as exc:
                errors.append(
                    {
                        "error_code": "FEATURE_FIELDS_MISSING",
                        "error_title": "缺少特征字段",
                        "user_message": "请指定用于建模的特征字段。",
                        "next_actions": ["从数值字段中选择一个或多个特征字段。", "多个字段可用逗号分隔。"],
                        "diagnostics": {"technical_detail": str(exc)},
                    }
                )
            if features_for_validation:
                errors.extend(validate_required_fields(manager, dataset_name, features_for_validation))
                errors.extend(validate_numeric_fields(manager, dataset_name, features_for_validation))
            try:
                record_for_validation = manager.get(dataset_name)
                if bool(spatial_validation) and record_for_validation.data_type == "vector":
                    errors.extend(validate_crs(manager, dataset_name))
                    errors.extend(validate_geometry_type(manager, dataset_name, ["Point"]))
            except Exception:
                pass
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if errors:
            return _tool_error_from_validation("train_xgboost_fusion_model", inputs, errors)

        if XGBRegressor is None:
            return tool_result_error(
                "train_xgboost_fusion_model",
                inputs=inputs,
                error_code="XGBOOST_UNAVAILABLE",
                error_title="XGBoost 依赖不可用",
                user_message="当前 Python 环境未安装 xgboost，无法训练 XGBoost 模型。",
                diagnostics={"dependency": "xgboost"},
                next_actions=["安装 xgboost 后重试。", "或先使用随机森林建模工具。"],
            ).to_json()

        df, source_gdf = _prepare_dataframe_with_geometry(dataset_name, manager)
        features = _parse_columns(feature_cols)
        resolved_columns = _resolve_existing_columns(df, [target_col, *features])
        target_col = resolved_columns[0]
        features = resolved_columns[1:]
        spatial_enabled = bool(spatial_validation and source_gdf is not None)
        spatial_gdf = None
        projected_crs = None

        if spatial_enabled:
            spatial_gdf, projected_crs = _append_spatial_coordinates(source_gdf.copy())
            if add_spatial_coordinates:
                for coord_col in ["__spatial_x__", "__spatial_y__"]:
                    df[coord_col] = spatial_gdf[coord_col]
                    if coord_col not in features:
                        features.append(coord_col)

        _validate_columns(df, [target_col, *features])
        df = _coerce_numeric_frame(df, [target_col, *features])

        valid_target = df[target_col].notna()
        if int(valid_target.sum()) < 20:
            raise ValueError(f"XGBoost 可用于训练的样本不足，当前仅 {int(valid_target.sum())} 条。")

        pred_col = f"{output_name}_xgb"
        cv_pred_col = f"{output_name}_xgb_spatial_cv"
        legacy_cv_pred_col = f"{output_name}_spatial_cv"
        cv_scope_col = f"{output_name}_spatial_cv_scope"
        cv_fold_col = f"{output_name}_spatial_cv_fold"
        cv_available_col = f"{output_name}_spatial_cv_available"
        resid_col = f"{output_name}_residual"
        residual_map_path: Path | None = None
        moran_table_name: str | None = None
        spatial_diag: dict[str, Any] | None = None

        model = _build_xgb_pipeline(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=random_state,
        )
        model.fit(df.loc[valid_target, features], df.loc[valid_target, target_col])
        df[pred_col] = model.predict(df[features])
        df[legacy_cv_pred_col] = np.nan
        df[cv_scope_col] = pd.Series(pd.NA, index=df.index, dtype="object")
        df[cv_fold_col] = pd.Series(pd.NA, index=df.index, dtype="object")
        df[cv_available_col] = False

        if spatial_enabled and spatial_gdf is not None:
            valid_spatial_gdf = spatial_gdf.loc[valid_target].copy()
            block_series = _make_spatial_blocks(valid_spatial_gdf, n_blocks=spatial_block_count, random_state=random_state)
            unique_blocks = int(block_series.nunique())
            if unique_blocks < 2:
                raise ValueError("空间分块数量不足，无法进行空间交叉验证。")

            df[cv_pred_col] = np.nan
            gkf = GroupKFold(n_splits=unique_blocks)
            valid_index = df.index[valid_target]
            x_valid = df.loc[valid_index, features]
            y_valid = df.loc[valid_index, target_col]
            groups = block_series.loc[valid_index]

            for fold_id, (train_idx, test_idx) in enumerate(gkf.split(x_valid, y_valid, groups=groups), start=1):
                fold_model = _build_xgb_pipeline(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    learning_rate=learning_rate,
                    subsample=subsample,
                    colsample_bytree=colsample_bytree,
                    random_state=random_state + fold_id,
                )
                train_index = valid_index[train_idx]
                test_index = valid_index[test_idx]
                fold_model.fit(df.loc[train_index, features], df.loc[train_index, target_col])
                fold_pred = fold_model.predict(df.loc[test_index, features])
                df.loc[test_index, cv_pred_col] = fold_pred
                df.loc[test_index, legacy_cv_pred_col] = fold_pred
                df.loc[test_index, cv_scope_col] = "holdout"
                df.loc[test_index, cv_fold_col] = int(fold_id)
                df.loc[test_index, cv_available_col] = True

            df[resid_col] = df[target_col] - df[cv_pred_col]
            metrics = {
                "spatial_cv": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, cv_pred_col]),
                "final_model_in_sample": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, pred_col]),
            }
            spatial_diag = _calc_global_moran_i(
                df[resid_col],
                spatial_gdf["__spatial_x__"],
                spatial_gdf["__spatial_y__"],
                k_neighbors=moran_k_neighbors,
                permutations=moran_permutations,
                random_state=random_state,
            )
            spatial_diag.update({
                "validation": "GroupKFold on spatial blocks",
                "spatial_block_count": int(unique_blocks),
                "projected_crs": projected_crs,
                "residual_column": resid_col,
                "cv_prediction_column": cv_pred_col,
                "legacy_cv_prediction_column": legacy_cv_pred_col,
                "cv_scope_column": cv_scope_col,
                "cv_fold_column": cv_fold_col,
            })
        else:
            if date_col and split_date:
                train_mask, test_mask = _split_train_test_by_date(df, date_col, split_date)
                metrics = _summarize_train_test_metrics(df, target_col, pred_col, train_mask & valid_target, test_mask & valid_target)
            else:
                metrics = {"overall": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, pred_col])}
            df[resid_col] = df[target_col] - df[pred_col]

        importances = model.named_steps["xgb"].feature_importances_
        importance_df = pd.DataFrame({"feature": features, "importance": importances}).sort_values("importance", ascending=False).reset_index(drop=True)

        if source_gdf is not None:
            result_gdf = source_gdf.copy()
            for col in df.columns:
                result_gdf[col] = df[col]
            saved_name = manager.put_vector(output_name, result_gdf, filename=f"{_artifact_safe_name(output_name)}.geojson")

            residual_map_path = manager.plot_dir / f"{_artifact_safe_name(output_name)}_residual_map.png"
            residual_plot_gdf = result_gdf.dropna(subset=[resid_col]).copy()
            if not residual_plot_gdf.empty:
                _save_vector_map_plot(residual_plot_gdf, residual_map_path, column=resid_col, title=f"{output_name} residual spatial distribution")
                manager.last_plot_path = str(residual_map_path)
                manager.log_operation("生成残差空间图", f"{output_name} -> {residual_map_path.name}", "plot")
        else:
            saved_name = manager.put_table(output_name, df)

        importance_name = manager.put_table(f"{output_name}_xgb_importance", importance_df)
        metrics_name = manager.put_table(f"{output_name}_xgb_metrics", pd.DataFrame([{"scope": key, **value} for key, value in metrics.items()]))
        if spatial_diag:
            moran_table_name = manager.put_table(f"{output_name}_moran_i", pd.DataFrame([spatial_diag]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_xgb_model.joblib"
        joblib.dump(model, model_path)

        meta_path = _save_json_artifact(manager, f"{output_name}_xgb_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "features": features,
            "prediction_column": pred_col,
            "cv_prediction_column": cv_pred_col if cv_pred_col in df.columns else None,
            "legacy_cv_prediction_column": legacy_cv_pred_col if legacy_cv_pred_col in df.columns else None,
            "cv_scope_column": cv_scope_col if cv_scope_col in df.columns else None,
            "cv_fold_column": cv_fold_col if cv_fold_col in df.columns else None,
            "cv_available_column": cv_available_col if cv_available_col in df.columns else None,
            "residual_column": resid_col,
            "split_date": split_date or None,
            "spatial_validation": bool(spatial_enabled),
            "params": {
                "n_estimators": int(n_estimators),
                "max_depth": int(max_depth),
                "learning_rate": float(learning_rate),
                "subsample": float(subsample),
                "colsample_bytree": float(colsample_bytree),
                "random_state": int(random_state),
                "spatial_block_count": int(spatial_block_count),
                "add_spatial_coordinates": bool(add_spatial_coordinates),
            },
            "metrics": metrics,
            "spatial_diagnostics": spatial_diag,
            "residual_map": str(residual_map_path) if residual_map_path else None,
        })
        manager.log_operation("XGBoost 融合训练", f"{dataset_name} -> {saved_name}", "model")

        reply_lines = [
            f"XGBoost 模型训练完成，结果数据集: {saved_name}，预测列: {pred_col}，残差列: {resid_col}。",
            f"特征重要性表: {importance_name}。",
            f"精度指标表: {metrics_name}。",
            f"模型文件: {model_path}。",
            f"摘要文件: {meta_path}。",
        ]
        if moran_table_name is not None:
            reply_lines.append(f"Moran's I 结果表: {moran_table_name}。")
        if residual_map_path is not None:
            reply_lines.append(f"残差空间分布图: {residual_map_path}。")
        if spatial_diag and spatial_diag.get("moran_i") is not None:
            detail = f"残差 Moran's I = {spatial_diag['moran_i']:.4f}"
            if spatial_diag.get("p_value") is not None:
                detail += f"，置换检验 p = {spatial_diag['p_value']:.4f}"
            reply_lines.append(detail + "。")
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} XGBoost predictions",
                description="XGBoost 预测结果数据集。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"table_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="XGBoost 精度指标表。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"table_{uuid4().hex[:10]}",
                path=str(manager.get(importance_name).path),
                type="feature_importance",
                title=f"{importance_name} feature importance",
                description="XGBoost 特征重要性表。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"model_{uuid4().hex[:10]}",
                path=str(model_path),
                type="model",
                title=f"{output_name} XGBoost model",
                description="训练后的 XGBoost 模型文件。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(meta_path),
                type="summary",
                title=f"{output_name} XGBoost summary",
                description="模型参数、指标和空间诊断摘要。",
                quality_status="created",
                preview_available=False,
            ),
        ]
        if moran_table_name is not None:
            artifacts.append(
                ArtifactInfo(
                    artifact_id=f"moran_{uuid4().hex[:10]}",
                    path=str(manager.get(moran_table_name).path),
                    type="diagnostics",
                    title=f"{moran_table_name} Moran's I",
                    description="残差空间自相关诊断表。",
                    quality_status="created",
                    preview_available=False,
                )
            )
        if residual_map_path is not None:
            artifacts.append(
                ArtifactInfo(
                    artifact_id=f"map_{uuid4().hex[:10]}",
                    path=str(residual_map_path),
                    type="map",
                    title=f"{output_name} residual map",
                    description="残差空间分布图。",
                    quality_status="created",
                    preview_available=True,
                )
            )
        task_id = f"train_xgboost_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("XGBoost", output_name)
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="XGBoost",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            figure_path=str(residual_map_path) if residual_map_path else "",
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts if item.get("artifact_id")],
            artifacts=artifact_dicts,
            metrics=metrics.get("spatial_cv") if isinstance(metrics.get("spatial_cv"), dict) else metrics.get("overall") if isinstance(metrics.get("overall"), dict) else metrics,
            diagnostics={"metrics": metrics, "spatial_diagnostics": spatial_diag, "features": features, "target_col": target_col},
        )
        return tool_result_ok(
            "train_xgboost_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "residual_column": resid_col,
                "metrics_dataset": metrics_name,
                "importance_dataset": importance_name,
                "moran_dataset": moran_table_name,
                "model_path": str(model_path),
                "summary_path": str(meta_path),
                "residual_map_path": str(residual_map_path) if residual_map_path else "",
            },
            artifacts=artifacts,
            summary="\n".join(reply_lines),
            diagnostics={"metrics": metrics, "spatial_diagnostics": spatial_diag},
            next_actions=["解释模型指标、特征重要性和残差空间分布。", "检查残差是否存在空间聚集，并考虑补充空间特征。"],
        ).to_json()


    @tool
    def train_lstm_fusion_model(
        dataset_name: str,
        target_col: str,
        dynamic_feature_cols: str,
        output_name: str,
        date_col: str,
        group_col: str = "",
        static_feature_cols: str = "",
        seq_len: int = 7,
        split_date: str = "",
        hidden_size: int = 32,
        num_layers: int = 1,
        epochs: int = 40,
        batch_size: int = 64,
        learning_rate: float = 0.001,
    ) -> str:
        """训练 LSTM 时序融合模型并输出预测结果与精度指标，适合刻画土壤水分时间记忆效应和动态变化。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "dynamic_feature_cols": dynamic_feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "group_col": group_col,
            "static_feature_cols": static_feature_cols,
            "seq_len": seq_len,
            "split_date": split_date,
            "hidden_size": hidden_size,
            "num_layers": num_layers,
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
        }
        dynamic_cols = _parse_columns(dynamic_feature_cols) if str(dynamic_feature_cols or "").strip() else []
        static_cols = _parse_columns(static_feature_cols) if static_feature_cols.strip() else []
        validation_errors: list[dict[str, Any]] = []
        validation_errors.extend(validate_dataset_exists(manager, dataset_name))
        validation_errors.extend(validate_model_target(manager, dataset_name, target_col))
        validation_errors.extend(validate_required_fields(manager, dataset_name, [date_col] if str(date_col or "").strip() else []))
        validation_errors.extend(validate_required_fields(manager, dataset_name, dynamic_cols + static_cols))
        validation_errors.extend(validate_numeric_fields(manager, dataset_name, dynamic_cols + static_cols))
        validation_errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not dynamic_cols:
            validation_errors.append({
                "error_code": "LSTM_DYNAMIC_FIELDS_MISSING",
                "error_title": "Missing dynamic feature fields",
                "user_message": "LSTM requires at least one dynamic feature field.",
                "next_actions": ["Provide time-varying numeric fields, for example precipitation, temperature or remote sensing variables."],
                "diagnostics": {},
            })
        if seq_len < 2:
            validation_errors.append({
                "error_code": "LSTM_SEQ_LEN_TOO_SMALL",
                "error_title": "Invalid sequence length",
                "user_message": "seq_len must be at least 2 for LSTM training.",
                "next_actions": ["Use seq_len=7 or another sequence length greater than 1."],
                "diagnostics": {"seq_len": seq_len},
            })
        if validation_errors:
            first = first_error(validation_errors) or {}
            return tool_result_error(
                "train_lstm_fusion_model",
                inputs=inputs,
                error_code=str(first.get("error_code") or "LSTM_PRECONDITION_FAILED"),
                error_title=str(first.get("error_title") or "LSTM precondition failed"),
                user_message=str(first.get("user_message") or "LSTM inputs are incomplete or invalid."),
                diagnostics=validation_diagnostics(validation_errors),
                next_actions=merge_next_actions(validation_errors),
                technical_detail=str(first.get("technical_detail") or ""),
            ).to_json()
        df = _prepare_dataframe(dataset_name, manager).copy()
        _validate_columns(df, [target_col, date_col, *dynamic_cols, *static_cols])

        seq_data = _build_lstm_sequences(
            df=df,
            date_col=date_col,
            target_col=target_col,
            dynamic_cols=dynamic_cols,
            static_cols=static_cols,
            group_col=group_col,
            seq_len=seq_len,
        )
        x_dyn = seq_data["x_dynamic"]
        x_sta = seq_data["x_static"]
        y = seq_data["y"]
        seq_dates = seq_data["dates"]
        orig_index = seq_data["orig_index"]

        if split_date:
            split_ts = pd.to_datetime(split_date, errors="coerce")
            if pd.isna(split_ts):
                raise ValueError(f"split_date 无法解析为日期: {split_date}")
            train_mask = seq_dates <= split_ts
            test_mask = seq_dates > split_ts
        else:
            train_mask = pd.Series([True] * len(seq_dates))
            test_mask = pd.Series([False] * len(seq_dates))

        if int(train_mask.sum()) < max(20, seq_len * 2):
            return tool_result_error(
                "train_lstm_fusion_model",
                inputs=inputs,
                error_code="LSTM_TRAINING_SAMPLE_TOO_SMALL",
                error_title="Training sample too small",
                user_message=f"LSTM has only {int(train_mask.sum())} usable sequence samples for training.",
                diagnostics={"usable_training_sequences": int(train_mask.sum()), "required_minimum": int(max(20, seq_len * 2))},
                next_actions=["Use a longer time series.", "Reduce seq_len if appropriate.", "Check missing values in target and dynamic feature fields."],
            ).to_json()

        x_dyn_train = x_dyn[train_mask.to_numpy()]
        x_sta_train = x_sta[train_mask.to_numpy()]
        y_train = y[train_mask.to_numpy()]

        dyn_mean = x_dyn_train.mean(axis=(0, 1), keepdims=True)
        dyn_std = x_dyn_train.std(axis=(0, 1), keepdims=True)
        dyn_std = np.where(dyn_std < 1e-6, 1.0, dyn_std)
        x_dyn_scaled = (x_dyn - dyn_mean) / dyn_std

        if static_cols:
            sta_mean = x_sta_train.mean(axis=0, keepdims=True)
            sta_std = x_sta_train.std(axis=0, keepdims=True)
            sta_std = np.where(sta_std < 1e-6, 1.0, sta_std)
            x_sta_scaled = (x_sta - sta_mean) / sta_std
        else:
            sta_mean = np.zeros((1, 0), dtype=np.float32)
            sta_std = np.ones((1, 0), dtype=np.float32)
            x_sta_scaled = x_sta

        y_mean = float(y_train.mean())
        y_std = float(y_train.std()) if float(y_train.std()) >= 1e-6 else 1.0
        y_scaled = (y - y_mean) / y_std

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _FusionLSTM(dynamic_dim=len(dynamic_cols), static_dim=len(static_cols), hidden_size=hidden_size, num_layers=num_layers).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        loss_fn = nn.MSELoss()

        train_dataset = TensorDataset(
            torch.tensor(x_dyn_scaled[train_mask.to_numpy()], dtype=torch.float32),
            torch.tensor(x_sta_scaled[train_mask.to_numpy()], dtype=torch.float32),
            torch.tensor(y_scaled[train_mask.to_numpy()], dtype=torch.float32),
        )
        train_loader = DataLoader(train_dataset, batch_size=min(batch_size, len(train_dataset)), shuffle=True)

        history_rows: list[dict[str, Any]] = []
        model.train()
        for epoch in range(1, epochs + 1):
            running = 0.0
            seen = 0
            for batch_dyn, batch_sta, batch_y in train_loader:
                batch_dyn = batch_dyn.to(device)
                batch_sta = batch_sta.to(device)
                batch_y = batch_y.to(device)
                optimizer.zero_grad()
                pred = model(batch_dyn, batch_sta if batch_sta.shape[1] > 0 else None)
                loss = loss_fn(pred, batch_y)
                loss.backward()
                optimizer.step()
                running += float(loss.item()) * len(batch_y)
                seen += len(batch_y)
            history_rows.append({"epoch": epoch, "train_mse": running / max(seen, 1)})

        model.eval()
        with torch.no_grad():
            pred_scaled = model(
                torch.tensor(x_dyn_scaled, dtype=torch.float32, device=device),
                torch.tensor(x_sta_scaled, dtype=torch.float32, device=device) if len(static_cols) else None,
            ).detach().cpu().numpy()
        pred_values = pred_scaled * y_std + y_mean

        result_df = df.copy()
        pred_col = f"{output_name}_lstm"
        result_df[pred_col] = np.nan
        for idx, pred_value in zip(orig_index, pred_values):
            result_df.loc[idx, pred_col] = float(pred_value)

        row_train_mask = pd.Series(False, index=result_df.index)
        row_test_mask = pd.Series(False, index=result_df.index)
        row_train_mask.loc[orig_index[train_mask.to_numpy()]] = True
        row_test_mask.loc[orig_index[test_mask.to_numpy()]] = True
        metrics = _summarize_train_test_metrics(result_df, target_col, pred_col, row_train_mask, row_test_mask if split_date else None)

        saved_name = manager.put_table(output_name, result_df)
        history_name = manager.put_table(f"{output_name}_lstm_history", pd.DataFrame(history_rows))
        metrics_name = manager.put_table(f"{output_name}_lstm_metrics", pd.DataFrame([{"scope": k, **v} for k, v in metrics.items()]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_lstm_model.pt"
        torch.save({
            "state_dict": model.state_dict(),
            "dynamic_cols": dynamic_cols,
            "static_cols": static_cols,
            "target_col": target_col,
            "seq_len": int(seq_len),
            "hidden_size": int(hidden_size),
            "num_layers": int(num_layers),
            "dyn_mean": dyn_mean.tolist(),
            "dyn_std": dyn_std.tolist(),
            "sta_mean": sta_mean.tolist(),
            "sta_std": sta_std.tolist(),
            "y_mean": y_mean,
            "y_std": y_std,
        }, model_path)
        meta_path = _save_json_artifact(manager, f"{output_name}_lstm_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "dynamic_cols": dynamic_cols,
            "static_cols": static_cols,
            "date_col": date_col,
            "group_col": group_col or None,
            "seq_len": int(seq_len),
            "prediction_column": pred_col,
            "split_date": split_date or None,
            "params": {
                "hidden_size": int(hidden_size),
                "num_layers": int(num_layers),
                "epochs": int(epochs),
                "batch_size": int(batch_size),
                "learning_rate": float(learning_rate),
            },
            "metrics": metrics,
            "sequence_count": int(len(orig_index)),
        })
        manager.log_operation("LSTM 融合训练", f"{dataset_name} -> {saved_name}", "model")
        task_id = f"train_lstm_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("LSTM", output_name)
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} LSTM predictions",
                description="LSTM prediction result table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"history_{uuid4().hex[:10]}",
                path=str(manager.get(history_name).path),
                type="training_history",
                title=f"{history_name} training history",
                description="LSTM training loss history.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"metrics_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="LSTM accuracy metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"model_{uuid4().hex[:10]}",
                path=str(model_path),
                type="model",
                title=f"{output_name} LSTM model",
                description="Trained LSTM model checkpoint.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(meta_path),
                type="summary",
                title=f"{output_name} LSTM summary",
                description="LSTM configuration and metrics summary.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="LSTM",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts],
            artifacts=artifact_dicts,
            metrics=metrics.get("test") if isinstance(metrics.get("test"), dict) else metrics.get("train") if isinstance(metrics.get("train"), dict) else metrics,
            diagnostics={
                "metrics": metrics,
                "dynamic_cols": dynamic_cols,
                "static_cols": static_cols,
                "target_col": target_col,
                "date_col": date_col,
                "sequence_count": int(len(orig_index)),
            },
        )
        return tool_result_ok(
            "train_lstm_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "history_dataset": history_name,
                "metrics_dataset": metrics_name,
                "model_path": str(model_path),
                "summary_path": str(meta_path),
            },
            artifacts=artifacts,
            summary=f"LSTM model training completed. Result dataset: {saved_name}. Metrics dataset: {metrics_name}.",
            diagnostics={"metrics": metrics, "sequence_count": int(len(orig_index))},
            next_actions=["Explain LSTM train/test metrics.", "Compare LSTM with RF/XGBoost and consider GCP uncertainty analysis."],
        ).to_json()


    @tool
    def generate_model_comparison_summary(metrics_dataset: str, output_prefix: str = "model_summary") -> str:
        """根据统一精度指标表或 GCP 指标表生成模型排序摘要、论文式结果段落和答辩用结论卡片。"""
        df = _prepare_dataframe(metrics_dataset, manager)
        highlights = _extract_metric_highlights(df, dataset_name=metrics_dataset)
        ranking = pd.DataFrame(highlights.get("ranking", []))
        ranking_name = manager.put_table(f"{output_prefix}_ranking", ranking, filename=f"{_artifact_safe_name(output_prefix)}_ranking.csv")
        metrics = highlights.get("metrics", [])
        family = highlights.get("family", "standard")
        lines = [f"# 模型比较摘要（来源：{metrics_dataset}）", ""]
        if ranking.empty:
            lines.append("当前指标表无法形成有效排序。")
        else:
            lines.append("## 综合排序")
            for idx, row in ranking.head(6).iterrows():
                lines.append(f"{idx + 1}. {row['predicted']}：综合排序分数 {row['rank_score']:.2f}")
            lines.append("")
        if family == 'gcp':
            if highlights.get("best_picp"):
                gap = highlights['best_picp'].get('coverage_gap')
                extra = f"，覆盖偏差={gap:.3f}" if isinstance(gap, (int, float)) else ""
                lines.append(f"- 覆盖率最优：{highlights['best_picp']['predicted']}（PICP={highlights['best_picp']['PICP']:.3f}{extra}）")
            if highlights.get("best_mpiw"):
                lines.append(f"- 区间最紧致：{highlights['best_mpiw']['predicted']}（MPIW={highlights['best_mpiw']['MPIW']:.3f}）")
            if highlights.get("best_is"):
                lines.append(f"- 区间评分最优：{highlights['best_is']['predicted']}（IS={highlights['best_is']['IS']:.3f}）")
            lines += [
                "",
                "## 论文式结果表述",
                "在统一 GCP 验证框架下，不同模型的区间预测质量存在明显差异。综合覆盖率、区间宽度、条件覆盖偏差和区间评分可见，排名靠前的方法在保持覆盖率接近名义水平的同时，具有更紧致的预测区间和更稳定的空间不确定性表征能力。",
                "",
                "## 答辩结论卡片",
                "1. GCP 结果不能只看覆盖率，还要同时考虑区间宽度与综合区间评分。",
                "2. 覆盖率接近名义水平且区间更窄，说明模型在可靠性与紧致性之间取得了更好的平衡。",
                "3. 建议将 GCP 结果与点预测精度结果联合汇报，体现模型准确性与可靠性。",
                "",
                "## 可引用指标字段",
                ", ".join(metrics) if metrics else "（未识别到指标列）",
            ]
        else:
            if highlights.get("best_r"):
                lines.append(f"- 相关性最优：{highlights['best_r']['predicted']}（R={highlights['best_r']['R']:.3f}）")
            if highlights.get("best_nse"):
                lines.append(f"- NSE 最优：{highlights['best_nse']['predicted']}（NSE={highlights['best_nse']['NSE']:.3f}）")
            if highlights.get("best_rmse"):
                lines.append(f"- RMSE 最优：{highlights['best_rmse']['predicted']}（RMSE={highlights['best_rmse']['RMSE']:.3f}）")
            lines += [
                "",
                "## 论文式结果表述",
                "在统一验证框架下，不同模型/产品的总体精度存在明显差异。综合相关性、误差和效率系数等指标可见，排名靠前的方法在独立验证期表现出更好的稳定性与泛化能力。建议在正文中同时报告最优模型的优势与局限，避免仅依据单一指标下结论。",
                "",
                "## 答辩结论卡片",
                "1. 最优模型并非只看单一指标，而是基于独立验证期综合排序。",
                "2. BTCH 提供了统计融合基线，RF/XGBoost 体现非线性拟合能力，LSTM 则体现时序记忆能力。",
                "3. 建议结合总体、时间维度和空间维度三类结果共同汇报。",
                "",
                "## 可引用指标字段",
                ", ".join(metrics) if metrics else "（未识别到指标列）",
            ]
        text = "\n".join(lines)
        md_path = _save_markdown_artifact(manager, f"{output_prefix}_summary", text)
        doc_name = manager.put_text_document(f"{output_prefix}_summary_doc", text, filename=f"{_artifact_safe_name(output_prefix)}_summary.txt")
        manager.log_operation("模型比较摘要", f"{metrics_dataset} -> {md_path.name}", "report")
        return f"模型比较摘要已生成: {md_path}。排序表数据集: {ranking_name}。文本数据集: {doc_name}"


    @tool
    def run_database_training_pipeline(
        output_prefix: str,
        target_col: str,
        feature_cols: str,
        sql: str = "",
        source_dataset: str = "",
        models: str = "btch,rf,xgboost,lstm",
        date_col: str = "",
        split_date: str = "",
        product_cols: str = "",
        observed_col: str = "",
        dynamic_feature_cols: str = "",
        static_feature_cols: str = "",
        group_col: str = "",
        lag_feature_cols: str = "",
        lag_steps: str = "1,3,7",
        rolling_windows: str = "3,7",
        seq_len: int = 7,
        stage: str = "",
        run_gcp: bool = True,
        gcp_alpha: float = 0.1,
        gcp_calibration_ratio: float = 0.3,
        gcp_selection: str = "latest",
        gcp_kernel: str = "gaussian",
        gcp_bandwidth: float = 0.0,
        gcp_lon_col: str = "",
        gcp_lat_col: str = "",
        gcp_target_scope: str = "holdout",
    ) -> str:
        """运行数据库驱动训练流水线：从 SQLite 或已有数据集生成训练表，显示完整步骤，并自动完成数据检查、特征构建、模型训练、指标汇总、图表与阶段材料输出。"""
        if not sql and not source_dataset:
            raise ValueError("请至少提供 sql 或 source_dataset 之一。")
        if not output_prefix.strip():
            raise ValueError("output_prefix 不能为空。")
        models_requested = [item.strip().lower() for item in re.split(r"[,;，\s]+", models or "") if item.strip()]
        models_requested = models_requested or ["btch", "rf", "xgboost", "lstm"]
        feature_list = _parse_columns(feature_cols)
        product_list = _parse_columns(product_cols) if product_cols.strip() else []
        observed_field = observed_col.strip() or target_col
        dynamic_cols_text = dynamic_feature_cols.strip() or feature_cols
        run_id = _make_pipeline_run_id(output_prefix)
        source_type = "sql" if sql.strip() else "dataset"
        source_value = sql.strip() if sql.strip() else source_dataset
        summary_seed = {
            "models_requested": models_requested,
            "target_col": target_col,
            "feature_cols": feature_list,
            "date_col": date_col or None,
            "split_date": split_date or None,
            "product_cols": product_list,
            "run_gcp": bool(run_gcp),
            "gcp_alpha": float(gcp_alpha),
            "gcp_calibration_ratio": float(gcp_calibration_ratio),
            "gcp_target_scope": gcp_target_scope or "holdout",
        }
        manager.start_pipeline_run(run_id, "database_training_pipeline", source_type, source_value, output_prefix, summary_seed)
        step_order = 0
        local_steps: list[dict[str, Any]] = []

        def record(step_name: str, status: str, input_summary: str, output_summary: str, detail: dict[str, Any] | None = None) -> None:
            nonlocal step_order
            step_order += 1
            detail = detail or {}
            manager.add_pipeline_step(run_id, step_order, step_name, status, input_summary, output_summary, detail)
            local_steps.append({
                "step_order": step_order,
                "step_name": step_name,
                "status": status,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "detail": detail,
            })

        try:
            if sql.strip():
                source_df = manager.query_database(sql)
                source_name = manager.put_table(f"{output_prefix}_source", source_df)
                record("生成训练表", "success", "从 SQLite 执行 SQL", f"得到训练表 {source_name}，{len(source_df)} 行", {"sql": sql, "dataset": source_name, "rows": int(len(source_df))})
            else:
                source_name = source_dataset
                source_df = _prepare_dataframe(source_name, manager)
                record("读取已有训练表", "success", f"数据集 {source_name}", f"读取 {len(source_df)} 行", {"dataset": source_name, "rows": int(len(source_df))})

            current_dataset = source_name
            profile_name = f"{output_prefix}_missing_profile"
            profile_missing_values.invoke({"dataset_name": current_dataset, "output_name": profile_name})
            record("数据体检", "success", f"检查 {current_dataset}", f"生成缺失值统计表 {profile_name}", {"profile_dataset": profile_name})

            if lag_feature_cols.strip() and date_col.strip():
                time_output = f"{output_prefix}_features"
                build_time_features.invoke({
                    "dataset_name": current_dataset,
                    "date_col": date_col,
                    "group_col": group_col,
                    "value_cols": lag_feature_cols,
                    "output_name": time_output,
                    "lags": lag_steps,
                    "rolling_windows": rolling_windows,
                })
                current_dataset = time_output
                record("构建时序特征", "success", f"base_cols={lag_feature_cols}", f"生成增强训练表 {time_output}", {"lag_steps": lag_steps, "rolling_windows": rolling_windows, "dataset": time_output})
            else:
                record("构建时序特征", "skipped", "未提供 lag_feature_cols 或 date_col", "跳过该步骤", {})

            combined_metric_rows: list[dict[str, Any]] = []
            created_outputs: dict[str, Any] = {"source_dataset": source_name, "working_dataset": current_dataset, "models": {}, "reports": {}, "charts": []}

            def _parsed_tool_success(raw: Any, step_name: str, input_summary: str) -> dict[str, Any] | None:
                parsed = parse_tool_result(raw)
                if parsed is not None and not parsed.get("ok"):
                    detail = {
                        "error_code": parsed.get("error_code"),
                        "user_message": parsed.get("user_message"),
                        "next_actions": parsed.get("next_actions"),
                        "diagnostics": parsed.get("diagnostics"),
                    }
                    record(step_name, "failed", input_summary, str(parsed.get("user_message") or parsed.get("error_code") or "tool failed"), detail)
                    return None
                return parsed or {}

            if "btch" in models_requested:
                if len(product_list) < 3:
                    record("BTCH 融合", "skipped", "产品列少于 3 个", "BTCH 至少需要 3 个产品列", {"product_cols": product_list})
                else:
                    btch_output = f"{output_prefix}_btch_result"
                    btch_fusion_model.invoke({
                        "dataset_name": current_dataset,
                        "product_cols": ",".join(product_list),
                        "output_name": btch_output,
                        "window_mode": "global",
                    })
                    pred_col = f"{btch_output}_btch"
                    created_outputs["models"]["btch"] = {"result_dataset": btch_output, "prediction_column": pred_col, "weights_dataset": f"{btch_output}_btch_weights"}
                    if observed_field:
                        btch_df = _prepare_dataframe(btch_output, manager)
                        _validate_columns(btch_df, [observed_field, pred_col])
                        metric_row = _calc_metrics(btch_df[observed_field], btch_df[pred_col])
                        metric_row.update({"predicted": pred_col, "model": "BTCH", "scope": "all"})
                        combined_metric_rows.append(metric_row)
                    record("BTCH 融合", "success", f"输入表 {current_dataset}", f"生成结果 {btch_output}", created_outputs["models"]["btch"])

            if "rf" in models_requested:
                rf_output = f"{output_prefix}_rf_result"
                rf_raw = train_rf_fusion_model.invoke({
                    "dataset_name": current_dataset,
                    "target_col": target_col,
                    "feature_cols": ",".join(feature_list),
                    "output_name": rf_output,
                    "date_col": date_col,
                    "split_date": split_date,
                })
                rf_result = _parsed_tool_success(rf_raw, "RF 融合训练", f"输入表 {current_dataset}")
                if rf_result is not None:
                    rf_outputs = rf_result.get("outputs") if isinstance(rf_result.get("outputs"), dict) else {}
                    rf_metrics_name = str(rf_outputs.get("metrics_dataset") or f"{rf_output}_rf_metrics")
                    rf_pred_col = str(rf_outputs.get("prediction_column") or f"{rf_output}_rf")
                    rf_metrics_df = _prepare_dataframe(rf_metrics_name, manager)
                    combined_metric_rows.append(_metric_row_with_label(rf_metrics_df, rf_pred_col, "RF"))
                    created_outputs["models"]["rf"] = {
                        "model_result_id": rf_outputs.get("model_result_id"),
                        "result_dataset": rf_outputs.get("result_dataset") or rf_output,
                        "prediction_column": rf_pred_col,
                        "metrics_dataset": rf_metrics_name,
                        "importance_dataset": rf_outputs.get("importance_dataset") or f"{rf_output}_rf_importance",
                    }
                    record("RF 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {rf_output}", created_outputs["models"]["rf"])

            if "xgboost" in models_requested or "xgb" in models_requested:
                try:
                    xgb_output = f"{output_prefix}_xgb_result"
                    xgb_raw = train_xgboost_fusion_model.invoke({
                        "dataset_name": current_dataset,
                        "target_col": target_col,
                        "feature_cols": ",".join(feature_list),
                        "output_name": xgb_output,
                        "date_col": date_col,
                        "split_date": split_date,
                    })
                    xgb_result = _parsed_tool_success(xgb_raw, "XGBoost 融合训练", f"输入表 {current_dataset}")
                    if xgb_result is not None:
                        xgb_outputs = xgb_result.get("outputs") if isinstance(xgb_result.get("outputs"), dict) else {}
                        xgb_metrics_name = str(xgb_outputs.get("metrics_dataset") or f"{xgb_output}_xgb_metrics")
                        xgb_pred_col = str(xgb_outputs.get("prediction_column") or f"{xgb_output}_xgb")
                        xgb_metrics_df = _prepare_dataframe(xgb_metrics_name, manager)
                        combined_metric_rows.append(_metric_row_with_label(xgb_metrics_df, xgb_pred_col, "XGBoost"))
                        created_outputs["models"]["xgboost"] = {
                            "model_result_id": xgb_outputs.get("model_result_id"),
                            "result_dataset": xgb_outputs.get("result_dataset") or xgb_output,
                            "prediction_column": xgb_pred_col,
                            "metrics_dataset": xgb_metrics_name,
                            "importance_dataset": xgb_outputs.get("importance_dataset") or f"{xgb_output}_xgb_importance",
                        }
                        record("XGBoost 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {xgb_output}", created_outputs["models"]["xgboost"])
                except Exception as exc:
                    record("XGBoost 融合训练", "failed", f"输入表 {current_dataset}", str(exc), {})

            if "lstm" in models_requested:
                if not date_col.strip():
                    record("LSTM 融合训练", "skipped", "未提供 date_col", "跳过 LSTM", {})
                else:
                    try:
                        lstm_output = f"{output_prefix}_lstm_result"
                        lstm_raw = train_lstm_fusion_model.invoke({
                            "dataset_name": current_dataset,
                            "target_col": target_col,
                            "dynamic_feature_cols": dynamic_cols_text,
                            "output_name": lstm_output,
                            "date_col": date_col,
                            "group_col": group_col,
                            "static_feature_cols": static_feature_cols,
                            "seq_len": int(seq_len),
                            "split_date": split_date,
                        })
                        lstm_result = _parsed_tool_success(lstm_raw, "LSTM 融合训练", f"输入表 {current_dataset}")
                        if lstm_result is not None:
                            lstm_outputs = lstm_result.get("outputs") if isinstance(lstm_result.get("outputs"), dict) else {}
                            lstm_metrics_name = str(lstm_outputs.get("metrics_dataset") or f"{lstm_output}_lstm_metrics")
                            lstm_pred_col = str(lstm_outputs.get("prediction_column") or f"{lstm_output}_lstm")
                            lstm_metrics_df = _prepare_dataframe(lstm_metrics_name, manager)
                            combined_metric_rows.append(_metric_row_with_label(lstm_metrics_df, lstm_pred_col, "LSTM"))
                            created_outputs["models"]["lstm"] = {
                                "model_result_id": lstm_outputs.get("model_result_id"),
                                "result_dataset": lstm_outputs.get("result_dataset") or lstm_output,
                                "prediction_column": lstm_pred_col,
                                "metrics_dataset": lstm_metrics_name,
                                "history_dataset": lstm_outputs.get("history_dataset") or f"{lstm_output}_lstm_history",
                            }
                            record("LSTM 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {lstm_output}", created_outputs["models"]["lstm"])
                    except Exception as exc:
                        record("LSTM 融合训练", "failed", f"输入表 {current_dataset}", str(exc), {})

            gcp_metric_rows: list[dict[str, Any]] = []
            created_outputs["gcp"] = {}

            def _save_subset_dataset(base_dataset: str, mask: pd.Series, subset_name: str) -> str:
                record = manager.get(base_dataset)
                if record.data_type == "vector":
                    subset_gdf = manager.get_vector(base_dataset).loc[mask].copy()
                    return manager.put_vector(subset_name, subset_gdf, filename=f"{_artifact_safe_name(subset_name)}.geojson")
                subset_df = _prepare_dataframe(base_dataset, manager).loc[mask].copy()
                return manager.put_table(subset_name, subset_df)

            if run_gcp and observed_field:
                gcp_scope = (gcp_target_scope or "holdout").strip().lower()
                if gcp_scope not in {"holdout", "all"}:
                    record("GCP 不确定性分析", "skipped", f"gcp_target_scope={gcp_target_scope}", "仅支持 holdout 或 all，已跳过", {})
                else:
                    for model_key, model_info in created_outputs["models"].items():
                        pred_col = str(model_info.get("prediction_column") or "").strip()
                        result_dataset = str(model_info.get("result_dataset") or "").strip()
                        if not pred_col or not result_dataset:
                            continue
                        try:
                            gcp_output = f"{output_prefix}_{model_key}_gcp"
                            calibration_dataset_name = result_dataset
                            target_dataset_name = ""
                            if gcp_scope == "holdout" and date_col.strip() and split_date.strip():
                                result_df = _prepare_dataframe(result_dataset, manager)
                                date_series = _ensure_datetime(result_df, date_col)
                                split_ts = pd.to_datetime(split_date)
                                calibration_mask = date_series <= split_ts
                                target_mask = date_series > split_ts
                                if int(calibration_mask.sum()) < 20 or int(target_mask.sum()) < 1:
                                    raise ValueError("按 split_date 划分后，校准集或目标集样本不足。")
                                calibration_dataset_name = _save_subset_dataset(result_dataset, calibration_mask, f"{result_dataset}_gcp_calibration")
                                target_dataset_name = _save_subset_dataset(result_dataset, target_mask, f"{result_dataset}_gcp_target")

                            gcp_raw = geographical_conformal_prediction.invoke({
                                "calibration_dataset": calibration_dataset_name,
                                "target_dataset_name": target_dataset_name,
                                "observed_col": observed_field,
                                "predicted_cols": pred_col,
                                "output_name": gcp_output,
                                "lon_col": gcp_lon_col,
                                "lat_col": gcp_lat_col,
                                "date_col": date_col,
                                "calibration_ratio": float(gcp_calibration_ratio),
                                "calibration_selection": gcp_selection,
                                "alpha": float(gcp_alpha),
                                "bandwidth": float(gcp_bandwidth),
                                "kernel": gcp_kernel,
                            })
                            gcp_result = _parsed_tool_success(gcp_raw, "GCP 不确定性分析", f"模型 {model_key} | 结果表 {result_dataset}")
                            if gcp_result is not None:
                                gcp_outputs = gcp_result.get("outputs") if isinstance(gcp_result.get("outputs"), dict) else {}
                                gcp_metrics_name = str(gcp_outputs.get("metrics_dataset") or f"{gcp_output}_gcp_metrics")
                                gcp_df = _prepare_dataframe(gcp_metrics_name, manager).copy()
                                gcp_df["model"] = model_key.upper() if model_key != "xgboost" else "XGBoost"
                                gcp_df["prediction_column"] = pred_col
                                gcp_metric_rows.extend(gcp_df.to_dict(orient="records"))
                                created_outputs["gcp"][model_key] = {
                                    "model_result_id": gcp_outputs.get("model_result_id"),
                                    "result_dataset": gcp_outputs.get("result_dataset") or gcp_output,
                                    "metrics_dataset": gcp_metrics_name,
                                    "prediction_column": pred_col,
                                    "calibration_dataset": calibration_dataset_name,
                                    "target_dataset": target_dataset_name or calibration_dataset_name,
                                }
                                record("GCP 不确定性分析", "success", f"模型 {model_key} | 结果表 {result_dataset}", f"生成区间结果 {gcp_output}", created_outputs["gcp"][model_key])
                        except Exception as exc:
                            record("GCP 不确定性分析", "failed", f"模型 {model_key} | 结果表 {result_dataset}", str(exc), {})
            else:
                record("GCP 不确定性分析", "skipped", f"run_gcp={run_gcp} observed_field={observed_field}", "未启用或缺少 observed_col，跳过 GCP", {})

            if gcp_metric_rows:
                gcp_metrics_dataset_name = manager.put_table(f"{output_prefix}_combined_gcp_metrics", pd.DataFrame(gcp_metric_rows))
                created_outputs["reports"]["gcp_metrics_dataset"] = gcp_metrics_dataset_name
                record("汇总 GCP 指标", "success", "收集各模型区间指标", f"生成统一 GCP 指标表 {gcp_metrics_dataset_name}", {"rows": int(len(gcp_metric_rows))})
                try:
                    gcp_chart_message = generate_thesis_charts.invoke({
                        "dataset_name": gcp_metrics_dataset_name,
                        "chart_type": "metric_bar",
                        "output_prefix": f"{output_prefix}_gcp_fig",
                        "title": f"{output_prefix} GCP 不确定性比较",
                    })
                    created_outputs["charts"].append(gcp_chart_message)
                    record("生成 GCP 图表", "success", f"GCP 指标表 {gcp_metrics_dataset_name}", "已生成 GCP 指标图与图注草稿", {"message": gcp_chart_message})
                except Exception as exc:
                    record("生成 GCP 图表", "failed", f"GCP 指标表 {gcp_metrics_dataset_name}", str(exc), {})

            if not combined_metric_rows:
                raise ValueError("流水线未生成任何可比较的模型指标，请检查输入字段和模型参数。")

            combined_metrics_df = pd.DataFrame(combined_metric_rows)
            metrics_dataset_name = manager.put_table(f"{output_prefix}_combined_metrics", combined_metrics_df)
            created_outputs["reports"]["metrics_dataset"] = metrics_dataset_name
            record("汇总模型指标", "success", "收集各模型指标", f"生成统一指标表 {metrics_dataset_name}", {"rows": int(len(combined_metrics_df))})

            try:
                charts_message = generate_thesis_charts.invoke({
                    "dataset_name": metrics_dataset_name,
                    "chart_type": "metric_bar",
                    "output_prefix": f"{output_prefix}_metrics_fig",
                    "title": f"{output_prefix} 模型精度比较",
                })
                created_outputs["charts"].append(charts_message)
                record("生成论文图表", "success", f"指标表 {metrics_dataset_name}", "已生成精度对比图与图注草稿", {"message": charts_message})
            except Exception as exc:
                record("生成论文图表", "failed", f"指标表 {metrics_dataset_name}", str(exc), {})

            summary_message = generate_model_comparison_summary.invoke({"metrics_dataset": metrics_dataset_name, "output_prefix": f"{output_prefix}_model_summary"})
            created_outputs["reports"]["comparison_summary"] = summary_message
            record("生成模型比较摘要", "success", f"指标表 {metrics_dataset_name}", "已生成摘要与结论卡片", {"message": summary_message})

            if created_outputs["reports"].get("gcp_metrics_dataset"):
                try:
                    gcp_summary_message = generate_model_comparison_summary.invoke({
                        "metrics_dataset": created_outputs["reports"]["gcp_metrics_dataset"],
                        "output_prefix": f"{output_prefix}_gcp_summary",
                    })
                    created_outputs["reports"]["gcp_comparison_summary"] = gcp_summary_message
                    record("生成 GCP 比较摘要", "success", f"指标表 {created_outputs['reports']['gcp_metrics_dataset']}", "已生成 GCP 摘要与结论卡片", {"message": gcp_summary_message})
                except Exception as exc:
                    record("生成 GCP 比较摘要", "failed", f"指标表 {created_outputs['reports']['gcp_metrics_dataset']}", str(exc), {})

            if stage.strip():
                stage_message = generate_stage_report.invoke({
                    "stage": stage,
                    "output_prefix": f"{output_prefix}_stage",
                    "metrics_dataset": metrics_dataset_name,
                    "gcp_metrics_dataset": created_outputs["reports"].get("gcp_metrics_dataset", ""),
                    "feature_importance_dataset": created_outputs["models"].get("rf", {}).get("importance_dataset") or created_outputs["models"].get("xgboost", {}).get("importance_dataset", ""),
                    "btch_weights_dataset": created_outputs["models"].get("btch", {}).get("weights_dataset", ""),
                })
                created_outputs["reports"]["stage_pack"] = stage_message
                record("生成阶段材料", "success", stage, "已生成阶段报告、提纲与问答库", {"message": stage_message})
            else:
                record("生成阶段材料", "skipped", "未提供 stage", "跳过阶段材料生成", {})

            final_detail = {
                "run_id": run_id,
                "pipeline_name": "database_training_pipeline",
                "status": "success",
                "source_type": source_type,
                "source_value": source_value,
                "output_prefix": output_prefix,
                "started_at": "",
                "finished_at": "",
                "steps": local_steps,
                "summary": created_outputs,
            }
            pipeline_md = _pipeline_steps_markdown(final_detail)
            pipeline_md_path = _save_markdown_artifact(manager, f"{output_prefix}_pipeline_report", pipeline_md)
            pipeline_doc_name = manager.put_text_document(f"{output_prefix}_pipeline_report_doc", pipeline_md, filename=f"{_artifact_safe_name(output_prefix)}_pipeline_report.txt")
            created_outputs["reports"]["pipeline_markdown"] = str(pipeline_md_path)
            created_outputs["reports"]["pipeline_document"] = pipeline_doc_name
            manager.finish_pipeline_run(run_id, "success", created_outputs)
            record("保存流程记录", "success", run_id, f"已生成流程文档 {pipeline_doc_name}", {"markdown": str(pipeline_md_path), "document": pipeline_doc_name})
            detail = manager.pipeline_run_detail(run_id) or final_detail
            latest_report = _pipeline_steps_markdown(detail)
            manager.put_text_document(f"{output_prefix}_pipeline_latest_doc", latest_report, filename=f"{_artifact_safe_name(output_prefix)}_pipeline_latest.txt")
            gcp_summary_line = ""
            if created_outputs["reports"].get("gcp_metrics_dataset"):
                gcp_summary_line = f"统一 GCP 指标表: {created_outputs['reports']['gcp_metrics_dataset']}。\n"
            return (
                f"数据库驱动训练流水线已完成。运行编号: {run_id}。\n"
                f"训练表: {created_outputs['source_dataset']}；工作表: {created_outputs['working_dataset']}。\n"
                f"统一指标表: {metrics_dataset_name}。\n"
                + gcp_summary_line
                + f"流程文档: {pipeline_md_path}（数据集 {pipeline_doc_name}）。\n"
                + "可继续用 show_pipeline_run 查看完整步骤，或用 list_pipeline_runs 查看历史记录。"
            )
        except Exception as exc:
            manager.finish_pipeline_run(run_id, "failed", {"error": str(exc), "partial_steps": local_steps})
            raise


    @tool
    def explain_database_training_pipeline(models: str = "btch,rf,xgboost,lstm") -> str:
        """用新手能看懂的方式说明数据库驱动训练流水线的完整步骤、输入、输出和推荐命令。"""
        model_list = [item.strip().lower() for item in re.split(r"[,;，\s]+", models or "") if item.strip()]
        data_preview = manager.list_database_objects()
        payload = {
            "pipeline_name": "数据库驱动训练流水线",
            "recommended_models": model_list or ["btch", "rf", "xgboost", "lstm"],
            "steps": [
                {"step": 1, "name": "准备数据", "what": "先把表格、矢量属性和文档同步到 SQLite，明确有哪些 SQL 表可直接使用。", "tools": ["database_status", "list_database_objects", "sync_all_to_database"]},
                {"step": 2, "name": "生成训练表", "what": "通过 SQL 或已有数据集生成训练表，推荐保证每一行都对应一个站点-日期样本。", "tools": ["query_workspace_database"]},
                {"step": 3, "name": "数据体检", "what": "检查字段、缺失值、时间列和目标列，必要时补 lag / rolling 特征。", "tools": ["profile_missing_values", "build_time_features"]},
                {"step": 4, "name": "模型训练", "what": "按需求运行 BTCH、RF、XGBoost、LSTM，并自动产出预测表、指标表和模型文件。", "tools": ["btch_fusion_model", "train_rf_fusion_model", "train_xgboost_fusion_model", "train_lstm_fusion_model"]},
                {"step": 5, "name": "不确定性分析", "what": "对模型输出自动执行 GCP（地理共形预测），生成预测区间、覆盖率和区间宽度指标。", "tools": ["geographical_conformal_prediction"]},
                {"step": 6, "name": "结果汇总", "what": "把各模型指标与 GCP 指标汇总成统一比较表，生成论文图表和阶段材料。", "tools": ["generate_thesis_charts", "generate_model_comparison_summary", "generate_stage_report"]},
                {"step": 7, "name": "查看流程记录", "what": "每次流水线运行都会写入数据库，可回看每一步的输入、输出和状态。", "tools": ["list_pipeline_runs", "show_pipeline_run"]},
                            ],
            "example": {
                "novice_prompt": "用数据库里的训练表做一条完整训练流水线，显示每一步处理过程，并比较 BTCH、RF、XGBoost、LSTM。",
                "typical_sql": "SELECT * FROM tbl_training_table",
            },
            "database_preview": data_preview,
        }
        return _json(payload)


    return [
        generic_xgboost_workflow,
        evaluate_prediction_accuracy,
        geographical_conformal_prediction,
        btch_fusion_model,
        train_rf_fusion_model,
        train_xgboost_fusion_model,
        train_lstm_fusion_model,
        generate_model_comparison_summary,
        run_database_training_pipeline,
        explain_database_training_pipeline,
    ]
