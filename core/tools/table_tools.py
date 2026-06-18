from __future__ import annotations

from typing import Any

from core.tools import table_helpers as _helpers

TABLE_TOOL_NAMES = {
    'detect_coordinate_fields',
    'profile_missing_values',
    'table_to_points',
    'build_time_features',
    'aggregate_time_series',
}

_LEGACY_DEPENDENCIES = (
    'ArtifactInfo',
    'SEASON_MAP',
    '_ensure_datetime',
    '_infer_coordinate_candidates',
    '_json',
    '_parse_columns',
    '_parse_int_list',
    '_prepare_dataframe',
    '_tool_error_from_validation',
    '_tool_internal_error',
    '_validate_columns',
    'gpd',
    'pd',
    'tool',
    'tool_result_error',
    'tool_result_ok',
    'uuid4',
    'validate_dataset_exists',
    'validate_numeric_fields',
    'validate_output_path',
    'validate_required_fields',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)

def build_table_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    @tool
    def detect_coordinate_fields(dataset_name: str) -> str:
        """自动识别表格或矢量属性中可能的经纬度或平面坐标字段，适合在 table_to_points 前或空间回归前先判断坐标信息。"""
        df = _prepare_dataframe(dataset_name, manager)
        result = _infer_coordinate_candidates(df)
        result["dataset"] = dataset_name
        if result["x_candidates"] and result["y_candidates"]:
            result["suggestion"] = (
                f"建议优先尝试 x={result['x_candidates'][0]['field']}，"
                f"y={result['y_candidates'][0]['field']}。"
            )
        else:
            result["suggestion"] = "未检测到明显的坐标字段，请先预览表格或手动指定。"
        return _json(result)


    @tool
    def profile_missing_values(dataset_name: str, output_name: str = "") -> str:
        """统计表格或矢量属性中的缺失值比例、唯一值数量和字段类型，适合建模前检查数据质量。"""
        df = _prepare_dataframe(dataset_name, manager)
        rows = []
        for col in df.columns:
            series = df[col]
            rows.append(
                {
                    "field": col,
                    "dtype": str(series.dtype),
                    "missing_count": int(series.isna().sum()),
                    "missing_ratio": float(series.isna().mean()) if len(series) else 0.0,
                    "unique_count": int(series.nunique(dropna=True)),
                }
            )
        result_df = pd.DataFrame(rows).sort_values(["missing_ratio", "field"], ascending=[False, True]).reset_index(drop=True)
        manager.log_operation("缺失值统计", dataset_name, "analysis")
        if output_name:
            saved_name = manager.put_table(output_name, result_df)
            return f"缺失值统计完成，结果表: {saved_name}，保存路径: {manager.get(saved_name).path}"
        return _json(result_df.to_dict(orient="records"))


    @tool
    def table_to_points(dataset_name: str, x_col: str, y_col: str, crs: str, output_name: str) -> str:
        """将表格按经纬度或平面坐标字段转换为点图层。"""
        inputs = {"dataset_name": dataset_name, "x_col": x_col, "y_col": y_col, "crs": crs, "output_name": output_name}
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not str(crs or "").strip():
            errors.append(
                {
                    "error_code": "CRS_REQUIRED",
                    "error_title": "缺少坐标系",
                    "user_message": "表格转点需要指定输出点图层的 CRS。",
                    "next_actions": ["如果坐标是经纬度，通常使用 EPSG:4326。", "如果是投影坐标，请填写对应 EPSG 代码。"],
                    "diagnostics": {},
                }
            )
        if not errors:
            try:
                record = manager.get(dataset_name)
                if record.data_type != "table":
                    return tool_result_error(
                        "table_to_points",
                        inputs=inputs,
                        error_code="UNSUPPORTED_DATASET_TYPE",
                        error_title="数据类型不支持",
                        user_message="table_to_points 只能处理表格数据。",
                        diagnostics={"dataset_type": record.data_type},
                        next_actions=["选择 CSV/Excel 表格数据，或直接使用已有矢量数据制图。"],
                    ).to_json()
            except Exception as exc:
                return _tool_internal_error("table_to_points", inputs, exc)
            errors.extend(validate_required_fields(manager, dataset_name, [x_col, y_col]))
            if not errors:
                errors.extend(validate_numeric_fields(manager, dataset_name, [x_col, y_col]))
        if errors:
            return _tool_error_from_validation("table_to_points", inputs, errors)
        try:
            df = manager.get_table(dataset_name)
            gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df[x_col], df[y_col]), crs=crs)
            saved_name = manager.put_vector(output_name, gdf)
            output_path = manager.get(saved_name).path
            manager.log_operation("琛ㄦ牸杞偣", f"{dataset_name} -> {saved_name} | {x_col},{y_col}", "analysis")
            return tool_result_ok(
                "table_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(gdf)), "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} point layer",
                        description=f"由表格 {dataset_name} 转换得到的点图层。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"表格转点完成，结果数据集 {saved_name}，点数量 {len(gdf)}。",
                diagnostics={"x_col": x_col, "y_col": y_col, "crs": crs, "row_count": int(len(df))},
                next_actions=["使用 plot_dataset 生成点位分布图。", "继续叠加边界或提取栅格值。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("table_to_points", inputs, exc)
        df = manager.get_table(dataset_name)
        if x_col not in df.columns or y_col not in df.columns:
            raise ValueError(f"字段不存在。可用字段: {list(df.columns)}")
        gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df[x_col], df[y_col]), crs=crs)
        saved_name = manager.put_vector(output_name, gdf)
        manager.log_operation("表格转点", f"{dataset_name} -> {saved_name} | {x_col},{y_col}", "analysis")
        return f"表格转点完成，结果: {saved_name}，要素数量: {len(gdf)}，保存路径: {manager.get(saved_name).path}"


    @tool
    def build_time_features(
        dataset_name: str,
        date_col: str,
        value_cols: str,
        output_name: str,
        group_col: str = "",
        lags: str = "1,3,7",
        rolling_windows: str = "3,7",
    ) -> str:
        """为时间序列表格构建滞后项与滚动统计特征，适合降水累积量、土壤水分记忆效应和 RF 或 LSTM 建模前特征工程。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        values = _parse_columns(value_cols)
        _validate_columns(df, values)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        df[date_col] = _ensure_datetime(df, date_col)
        lag_list = _parse_int_list(lags, [1, 3, 7])
        rolling_list = _parse_int_list(rolling_windows, [3, 7])

        sort_cols = [group_col, date_col] if group_col else [date_col]
        df = df.sort_values(sort_cols).reset_index(drop=True)

        def _transform(group: pd.DataFrame) -> pd.DataFrame:
            out = group.copy()
            for col in values:
                numeric = pd.to_numeric(out[col], errors="coerce")
                for lag in lag_list:
                    out[f"{col}_lag_{lag}"] = numeric.shift(lag)
                for window in rolling_list:
                    out[f"{col}_rollmean_{window}"] = numeric.rolling(window=window, min_periods=1).mean()
                    out[f"{col}_rollsum_{window}"] = numeric.rolling(window=window, min_periods=1).sum()
            return out

        result = df.groupby(group_col, group_keys=False).apply(_transform) if group_col else _transform(df)
        saved_name = manager.put_table(output_name, result)
        manager.log_operation("构建时间特征", f"{dataset_name} -> {saved_name}", "analysis")
        return f"时间特征构建完成，结果表: {saved_name}，新增字段已包含 lag / rollmean / rollsum，保存路径: {manager.get(saved_name).path}"


    @tool
    def aggregate_time_series(
        dataset_name: str,
        date_col: str,
        value_cols: str,
        output_name: str,
        freq: str = "month",
        agg: str = "mean",
        group_col: str = "",
    ) -> str:
        """按月、季节、季度、年等时间尺度聚合时间序列表格，适合月尺度或季节尺度结果分析。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        values = _parse_columns(value_cols)
        _validate_columns(df, values)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        allowed_agg = {"mean", "sum", "min", "max", "median"}
        if agg not in allowed_agg:
            raise ValueError(f"agg 必须是 {sorted(allowed_agg)} 之一")
        df[date_col] = _ensure_datetime(df, date_col)
        for col in values:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        freq_key = freq.strip().lower()
        if freq_key in {"month", "monthly", "m"}:
            groupers = [pd.Grouper(key=date_col, freq="MS")]
        elif freq_key in {"quarter", "quarterly", "q"}:
            groupers = [pd.Grouper(key=date_col, freq="QS")]
        elif freq_key in {"year", "yearly", "y", "annual"}:
            groupers = [pd.Grouper(key=date_col, freq="YS")]
        elif freq_key in {"week", "weekly", "w"}:
            groupers = [pd.Grouper(key=date_col, freq="W-MON")]
        elif freq_key in {"season", "seasonal"}:
            df["season"] = df[date_col].dt.month.map(SEASON_MAP)
            df["season_year"] = df[date_col].dt.year + (df[date_col].dt.month == 12).astype(int)
            groupers = ["season_year", "season"]
        else:
            raise ValueError("freq 目前支持 month、quarter、year、week、season。")

        if group_col:
            groupers = [group_col, *groupers]
        grouped = df.groupby(groupers, dropna=False)[values].agg(agg).reset_index()
        saved_name = manager.put_table(output_name, grouped)
        manager.log_operation("时间聚合", f"{dataset_name} -> {saved_name} | {freq}/{agg}", "analysis")
        return f"时间聚合完成，结果表: {saved_name}，频率: {freq}，聚合方式: {agg}，保存路径: {manager.get(saved_name).path}"


    return [
        detect_coordinate_fields,
        profile_missing_values,
        table_to_points,
        build_time_features,
        aggregate_time_series,
    ]
