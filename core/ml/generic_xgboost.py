from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, RandomizedSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder

from core.data_manager import DataManager
from core.model_results import generate_model_result_id
from core.tool_contracts import ToolResult, tool_result_error, tool_result_ok

from .modeling_advisor import build_default_modeling_advisor_client, build_zhipu_modeling_advice, modeling_advisor_enabled
from .modeling_profile import build_modeling_profile
from .raster_stack import build_raster_stack, stack_training_frame, write_prediction_raster
from .spatial_features import extract_raster_features, parse_name_list

try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover - dependency availability is environment-specific
    XGBClassifier = None
    XGBRegressor = None


NON_FEATURE_FIELDS = {"id", "name", "date", "time", "lon", "lng", "long", "longitude", "lat", "latitude", "geometry", "geom", "target"}
SENSITIVE_TOKENS = {".env", "secret", "secrets", "cookies", "storage_state", "workspace.db"}


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("._-")
    return clean or f"xgb_{uuid4().hex[:8]}"


def _map_layer_id(dataset_name: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(dataset_name or "").strip()).strip("_").lower()
    return f"dataset_{clean or 'layer'}"


def _artifact(path: Path, type_: str, title: str, *, dataset_name: str = "", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    merged_meta = dict(meta or {})
    if dataset_name:
        merged_meta.update({"dataset_name": dataset_name, "map_ready": type_ in {"geojson", "raster"}, "map_layer_id": _map_layer_id(dataset_name)})
    mime_type = {
        "csv": "text/csv",
        "geojson": "application/geo+json",
        "metrics": "text/csv",
        "feature_importance": "text/csv",
        "model": "application/octet-stream",
        "summary": "application/json",
        "raster": "image/tiff",
        "png": "image/png",
    }.get(type_, "")
    return {
        "artifact_id": f"artifact_{uuid4().hex[:10]}",
        "path": str(path),
        "type": type_,
        "title": title,
        "quality_status": "generated",
        "preview_available": type_ in {"geojson", "raster", "png"},
        "mime_type": mime_type,
        "source_tool": "generic_xgboost_workflow",
        "meta": merged_meta,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    return value


def _blocked_sensitive(inputs: dict[str, Any]) -> str:
    for key, value in inputs.items():
        text = str(value or "").lower()
        if any(token in text for token in SENSITIVE_TOKENS):
            return key
    return ""


def _dataframe_from_dataset(manager: DataManager, dataset_name: str) -> tuple[pd.DataFrame, gpd.GeoDataFrame | None, str]:
    record = manager.get(dataset_name)
    if record.data_type == "table":
        return manager.get_table(dataset_name), None, "table_vector"
    if record.data_type == "vector":
        gdf = manager.get_vector(dataset_name)
        return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore")), gdf, "table_vector"
    raise TypeError(f"{dataset_name} is not a table or vector dataset")


def _feature_candidates(df: pd.DataFrame, target_col: str) -> list[str]:
    result: list[str] = []
    target_norm = str(target_col).lower()
    for col in df.columns:
        norm = str(col).lower()
        if norm == target_norm or norm in NON_FEATURE_FIELDS or norm.endswith("_id"):
            continue
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_categorical_dtype(df[col]):
            result.append(str(col))
    return result


def _infer_task_type(y: pd.Series, requested: str) -> str:
    requested = str(requested or "auto").lower()
    if requested in {"regression", "classification"}:
        return requested
    non_null = y.dropna()
    unique_count = int(non_null.nunique(dropna=True))
    if unique_count <= 1:
        return "ambiguous"
    if pd.api.types.is_numeric_dtype(non_null):
        if pd.api.types.is_integer_dtype(non_null) and unique_count <= 10:
            return "classification"
        if pd.api.types.is_float_dtype(non_null) and unique_count <= 3:
            return "ambiguous"
        return "regression"
    if unique_count <= max(30, int(len(non_null) * 0.5)):
        return "classification"
    return "ambiguous"


def _make_pipeline(feature_df: pd.DataFrame, model_type: str, random_state: int) -> tuple[Pipeline, list[str], list[str]]:
    categorical = [c for c in feature_df.columns if not pd.api.types.is_numeric_dtype(feature_df[c]) or pd.api.types.is_bool_dtype(feature_df[c])]
    numeric = [c for c in feature_df.columns if c not in categorical]
    encoder_kwargs = {"handle_unknown": "ignore"}
    try:
        encoder = OneHotEncoder(**encoder_kwargs, sparse_output=False)
    except TypeError:  # scikit-learn < 1.2
        encoder = OneHotEncoder(**encoder_kwargs, sparse=False)
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric),
            ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", encoder)]), categorical),
        ],
        remainder="drop",
    )
    if model_type == "classification":
        if XGBClassifier is None:
            raise RuntimeError("XGBOOST_UNAVAILABLE")
        model = XGBClassifier(
            n_estimators=80,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            random_state=random_state,
            n_jobs=1,
        )
    else:
        if XGBRegressor is None:
            raise RuntimeError("XGBOOST_UNAVAILABLE")
        model = XGBRegressor(
            n_estimators=80,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=random_state,
            n_jobs=1,
        )
    return Pipeline([("preprocess", preprocessor), ("model", model)]), numeric, categorical


def _apply_auto_tuning(
    pipeline: Pipeline,
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    *,
    model_type: str,
    tuning_budget: str,
    random_state: int,
) -> tuple[Pipeline, dict[str, Any]]:
    budget = str(tuning_budget or "small").lower()
    n_iter = {"small": 4, "medium": 8, "large": 16}.get(budget, 4)
    param_distributions = {
        "model__n_estimators": [60, 100, 160, 240],
        "model__max_depth": [2, 3, 4, 5],
        "model__learning_rate": [0.03, 0.06, 0.1, 0.15],
        "model__subsample": [0.75, 0.9, 1.0],
        "model__colsample_bytree": [0.75, 0.9, 1.0],
    }
    scoring = "f1_macro" if model_type == "classification" else "neg_root_mean_squared_error"
    cv = 3 if len(x_train) >= 30 else 2
    search = RandomizedSearchCV(
        pipeline,
        param_distributions=param_distributions,
        n_iter=n_iter,
        scoring=scoring,
        cv=cv,
        random_state=random_state,
        n_jobs=1,
        error_score="raise",
    )
    search.fit(x_train, y_train)
    return search.best_estimator_, {
        "enabled": True,
        "status": "completed",
        "budget": budget,
        "n_iter": n_iter,
        "cv": cv,
        "scoring": scoring,
        "best_params": search.best_params_,
        "best_score": _json_safe(search.best_score_),
    }


def _shap_status(pipeline: Pipeline, x_sample: pd.DataFrame, *, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "status": "disabled"}
    try:
        import shap  # type: ignore

        transformed = pipeline.named_steps["preprocess"].transform(x_sample)
        explainer = shap.TreeExplainer(pipeline.named_steps["model"])
        values = explainer.shap_values(transformed)
        arr = np.asarray(values)
        return {"enabled": True, "status": "computed", "sample_count": int(len(x_sample)), "shape": list(arr.shape)}
    except Exception as exc:
        return {"enabled": True, "status": "unavailable", "reason": exc.__class__.__name__}


def _modeling_advisor_status(profile: dict[str, Any], *, enabled: bool | None, client: Any | None) -> dict[str, Any]:
    if not modeling_advisor_enabled(enabled):
        return {"enabled": False, "status": "disabled"}
    advisor_client = client or build_default_modeling_advisor_client()
    if advisor_client is None:
        return {"enabled": True, "status": "fallback_local", "error": "advisor_client_unavailable"}
    result = build_zhipu_modeling_advice(profile, client=advisor_client)
    return {"enabled": True, **{key: value for key, value in result.items() if key != "payload_profile"}}


def _spatial_group_labels(df: pd.DataFrame, lon_col: str, lat_col: str) -> np.ndarray:
    bins = min(5, max(2, int(np.sqrt(len(df)) // 2 or 2)))
    lon_bins = pd.qcut(pd.to_numeric(df[lon_col], errors="coerce").rank(method="first"), q=bins, duplicates="drop")
    lat_bins = pd.qcut(pd.to_numeric(df[lat_col], errors="coerce").rank(method="first"), q=bins, duplicates="drop")
    return np.asarray([f"{lon}_{lat}" for lon, lat in zip(lon_bins.astype(str), lat_bins.astype(str))])


def _split_indices(
    df: pd.DataFrame,
    *,
    split_method: str,
    test_size: float,
    random_state: int,
    group_col: str = "",
    date_col: str = "",
    lon_col: str = "",
    lat_col: str = "",
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    idx = np.arange(len(df))
    method = str(split_method or "auto").lower()
    has_date = bool(date_col and date_col in df.columns)
    has_space = bool(lon_col and lat_col and lon_col in df.columns and lat_col in df.columns)
    if method in {"spatiotemporal", "auto"} and has_date and has_space:
        ordered = pd.to_datetime(df[date_col], errors="coerce").sort_values().index.to_numpy()
        cut = max(1, int(len(ordered) * (1 - test_size)))
        if cut >= len(ordered):
            cut = max(1, len(ordered) - 1)
        return (
            ordered[:cut],
            ordered[cut:],
            {"method": "spatiotemporal", "date_col": date_col, "lon_col": lon_col, "lat_col": lat_col, "test_size": test_size},
        )
    if method in {"spatial", "spatial_block", "auto"} and has_space and len(df) >= 10:
        groups = _spatial_group_labels(df, lon_col, lat_col)
        if len(set(groups)) > 1:
            splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
            train, test = next(splitter.split(df, groups=groups))
            return train, test, {"method": "spatial", "lon_col": lon_col, "lat_col": lat_col, "test_size": test_size}
    if (method in {"group", "auto"} and group_col and group_col in df.columns and df[group_col].nunique() > 1):
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        train, test = next(splitter.split(df, groups=df[group_col]))
        return train, test, {"method": "group", "group_col": group_col, "test_size": test_size}
    if method in {"date", "auto"} and date_col and date_col in df.columns:
        ordered = df[date_col].sort_values().index.to_numpy()
        cut = max(1, int(len(ordered) * (1 - test_size)))
        return ordered[:cut], ordered[cut:], {"method": "date", "date_col": date_col, "test_size": test_size}
    train, test = train_test_split(idx, test_size=test_size, random_state=random_state)
    return np.asarray(train), np.asarray(test), {"method": "random", "test_size": test_size, "random_state": random_state}


def _metrics(model_type: str, y_true: np.ndarray, pred: np.ndarray, proba: np.ndarray | None = None) -> dict[str, Any]:
    if model_type == "regression":
        rmse = float(np.sqrt(mean_squared_error(y_true, pred)))
        return {"R2": float(r2_score(y_true, pred)), "RMSE": float(rmse), "MAE": float(mean_absolute_error(y_true, pred))}
    labels = np.unique(np.concatenate([np.asarray(y_true), np.asarray(pred)]))
    average = "binary" if len(labels) == 2 else "macro"
    auc: float | None = None
    try:
        if proba is not None and len(labels) == 2:
            auc = float(roc_auc_score(y_true, proba[:, 1]))
    except Exception:
        auc = None
    return {
        "Accuracy": float(accuracy_score(y_true, pred)),
        "Precision": float(precision_score(y_true, pred, average=average, zero_division=0)),
        "Recall": float(recall_score(y_true, pred, average=average, zero_division=0)),
        "F1": float(f1_score(y_true, pred, average=average, zero_division=0)),
        "AUC": auc,
    }


def _feature_importance(pipeline: Pipeline, features: list[str]) -> pd.DataFrame:
    model = pipeline.named_steps["model"]
    preprocessor = pipeline.named_steps["preprocess"]
    try:
        names = [str(v) for v in preprocessor.get_feature_names_out()]
    except Exception:
        names = features
    values = getattr(model, "feature_importances_", np.zeros(len(names), dtype=float))
    rows = []
    for name, score in zip(names, values):
        original = str(name).split("__", 1)[-1]
        if original.startswith("cat_"):
            original = original[4:].split("_", 1)[0]
        rows.append({"feature": original, "encoded_feature": str(name), "importance": float(score)})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["feature", "importance", "encoded_feature"])
    grouped = df.groupby("feature", as_index=False)["importance"].sum().sort_values("importance", ascending=False)
    encoded = df.sort_values("importance", ascending=False).drop_duplicates("feature")[["feature", "encoded_feature"]]
    return grouped.merge(encoded, on="feature", how="left")


def _fit_table_model(
    manager: DataManager,
    *,
    df: pd.DataFrame,
    gdf: gpd.GeoDataFrame | None,
    target_col: str,
    feature_cols: list[str],
    output_name: str,
    task_mode: str,
    task_type: str,
    group_col: str,
    date_col: str,
    lon_col: str,
    lat_col: str,
    split_method: str,
    test_size: float,
    random_state: int,
    max_training_samples: int,
    auto_tune: bool,
    tuning_budget: str,
    enable_shap: bool,
    modeling_advisor: dict[str, Any],
    extra_diagnostics: dict[str, Any] | None = None,
) -> ToolResult:
    inputs = {
        "target_col": target_col,
        "feature_cols": ",".join(feature_cols),
        "output_name": output_name,
        "task_mode": task_mode,
        "task_type": task_type,
    }
    if target_col not in df.columns:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="TARGET_REQUIRED",
            error_title="Target variable is required",
            user_message="请指定可用于训练的目标变量 target。",
            diagnostics={"required_inputs": ["target"], "available_fields": list(df.columns)},
            next_actions=["在 target_col 中填写目标字段名。"],
        )
    if not feature_cols:
        feature_cols = _feature_candidates(df, target_col)
    missing = [col for col in feature_cols if col not in df.columns]
    if missing:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="FEATURE_FIELD_MISSING",
            error_title="Feature fields are missing",
            user_message="部分特征字段不存在，请检查 feature_cols。",
            diagnostics={"missing_features": missing, "available_fields": list(df.columns)},
        )
    work = df[[target_col] + feature_cols].copy()
    mask = work[target_col].notna()
    work = work.loc[mask].reset_index(drop=True)
    source_indices = df.index[mask].to_numpy()
    if len(work) < 8:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="INSUFFICIENT_TRAINING_SAMPLES",
            error_title="Insufficient training samples",
            user_message="有效训练样本太少，无法可靠训练 XGBoost。",
            diagnostics={"sample_count": int(len(work))},
        )
    if len(work) > max_training_samples:
        work = work.sample(n=max_training_samples, random_state=random_state).reset_index(drop=True)
        source_indices = source_indices[work.index.to_numpy()]
    model_type = _infer_task_type(work[target_col], task_type)
    if model_type == "ambiguous":
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="TASK_TYPE_AMBIGUOUS",
            error_title="Task type is ambiguous",
            user_message="目标变量类型不清楚，请指定 task_type 为 regression 或 classification。",
            diagnostics={"target_col": target_col, "unique_values": int(work[target_col].nunique(dropna=True))},
        )
    x = work[feature_cols]
    y_raw = work[target_col]
    label_encoder: LabelEncoder | None = None
    y = y_raw.to_numpy()
    if model_type == "classification":
        label_encoder = LabelEncoder()
        y = label_encoder.fit_transform(y_raw.astype(str))
    split_df = df.loc[source_indices].reset_index(drop=True)
    fields_lower = {str(col).lower(): str(col) for col in split_df.columns}
    resolved_lon_col = lon_col or fields_lower.get("lon") or fields_lower.get("lng") or fields_lower.get("longitude") or fields_lower.get("x") or ""
    resolved_lat_col = lat_col or fields_lower.get("lat") or fields_lower.get("latitude") or fields_lower.get("y") or ""
    train_idx, test_idx, split_info = _split_indices(
        split_df,
        split_method=split_method,
        test_size=test_size,
        random_state=random_state,
        group_col=group_col,
        date_col=date_col,
        lon_col=resolved_lon_col,
        lat_col=resolved_lat_col,
    )
    pipeline, numeric_cols, categorical_cols = _make_pipeline(x, model_type, random_state)
    tuning_info = {"enabled": bool(auto_tune), "status": "disabled"}
    if auto_tune:
        try:
            pipeline, tuning_info = _apply_auto_tuning(
                pipeline,
                x.iloc[train_idx],
                y[train_idx],
                model_type=model_type,
                tuning_budget=tuning_budget,
                random_state=random_state,
            )
        except Exception as exc:
            tuning_info = {"enabled": True, "status": "failed", "reason": exc.__class__.__name__}
            pipeline.fit(x.iloc[train_idx], y[train_idx])
    else:
        pipeline.fit(x.iloc[train_idx], y[train_idx])
    pred = pipeline.predict(x.iloc[test_idx])
    proba = pipeline.predict_proba(x.iloc[test_idx]) if model_type == "classification" and hasattr(pipeline, "predict_proba") else None
    metrics = _metrics(model_type, y[test_idx], pred, proba)
    all_pred = pipeline.predict(x)
    if label_encoder is not None:
        all_pred_labels = label_encoder.inverse_transform(all_pred.astype(int))
        validation_pred_labels = label_encoder.inverse_transform(pred.astype(int))
    else:
        all_pred_labels = all_pred
        validation_pred_labels = pred
    prediction_col = "xgb_prediction"
    residual_col = "xgb_residual"
    validation_prediction_col = "xgb_validation_prediction"
    validation_residual_col = "xgb_validation_residual"
    validation_fold_col = "xgb_validation_fold"
    validation_role_col = "xgb_validation_role"
    validation_method = str(split_info.get("method") or "random")
    validation_predictions = pd.Series(pd.NA, index=range(len(work)), dtype="object")
    validation_predictions.iloc[test_idx] = list(validation_pred_labels)
    validation_roles = pd.Series("train", index=range(len(work)), dtype="object")
    validation_roles.iloc[test_idx] = "test"
    validation_folds = pd.Series(0, index=range(len(work)), dtype="Int64")
    validation_folds.iloc[test_idx] = 1
    if model_type == "regression":
        all_residuals = pd.to_numeric(y_raw.reset_index(drop=True), errors="coerce") - pd.to_numeric(pd.Series(all_pred_labels), errors="coerce")
        validation_residuals = pd.Series(pd.NA, index=range(len(work)), dtype="object")
        validation_residuals.iloc[test_idx] = (
            pd.to_numeric(pd.Series(y_raw.reset_index(drop=True).iloc[test_idx]), errors="coerce").to_numpy()
            - pd.to_numeric(pd.Series(validation_pred_labels), errors="coerce").to_numpy()
        )
    else:
        all_residuals = pd.Series(pd.NA, index=range(len(work)), dtype="object")
        validation_residuals = pd.Series(pd.NA, index=range(len(work)), dtype="object")

    def _add_method_columns(frame: pd.DataFrame) -> pd.DataFrame:
        frame[prediction_col] = all_pred_labels
        frame[residual_col] = all_residuals.to_numpy()
        frame[validation_prediction_col] = validation_predictions.to_numpy()
        frame[validation_residual_col] = validation_residuals.to_numpy()
        frame[validation_fold_col] = validation_folds.to_numpy()
        frame[validation_role_col] = validation_roles.to_numpy()
        return frame

    if gdf is not None:
        result_gdf = gdf.iloc[source_indices].copy()
        result_gdf = _add_method_columns(result_gdf)
        result_dataset = manager.put_vector(output_name, result_gdf, filename=f"{_safe_name(output_name)}.geojson")
        result_path = Path(manager.get(result_dataset).path)
        result_artifact = _artifact(result_path, "geojson", f"{output_name}.geojson", dataset_name=result_dataset, meta={"layer_kind": "prediction"})
    else:
        result_df = df.iloc[source_indices].copy()
        result_df = _add_method_columns(result_df)
        result_dataset = manager.put_table(output_name, result_df, filename=f"{_safe_name(output_name)}.csv")
        result_path = Path(manager.get(result_dataset).path)
        result_artifact = _artifact(result_path, "csv", f"{output_name}.csv", dataset_name=result_dataset)
    importance_df = _feature_importance(pipeline, feature_cols)
    shap_info = _shap_status(pipeline, x.iloc[train_idx[: min(len(train_idx), 200)]], enabled=enable_shap)
    metrics_dataset = manager.put_table(f"{output_name}_metrics", pd.DataFrame([metrics]))
    importance_dataset = manager.put_table(f"{output_name}_feature_importance", importance_df)
    model_path = manager.derived_dir / f"{_safe_name(output_name)}_model.joblib"
    joblib.dump(
        {
            "pipeline": pipeline,
            "label_encoder": label_encoder,
            "features": feature_cols,
            "target": target_col,
            "numeric_features": numeric_cols,
            "categorical_features": categorical_cols,
        },
        model_path,
    )
    summary_path = manager.derived_dir / f"{_safe_name(output_name)}_summary.json"
    modeling_profile = build_modeling_profile(df, dataset_name=output_name, data_type="vector" if gdf is not None else "table")
    coordinate_columns = {"lon": resolved_lon_col, "lat": resolved_lat_col} if resolved_lon_col and resolved_lat_col else {}
    time_column = date_col if date_col and date_col in split_df.columns else ""
    feature_semantics = {
        "target": target_col,
        "feature_columns": feature_cols,
        "numeric_features": numeric_cols,
        "categorical_features": categorical_cols,
        "coordinate_features": [col for col in [resolved_lon_col, resolved_lat_col] if col and col in feature_cols],
        "time_feature": time_column,
        "group_feature": group_col if group_col and group_col in split_df.columns else "",
    }
    limitations = []
    if validation_method == "random":
        limitations.append("random_split_validation")
    method_metadata = {
        "validation_method": validation_method,
        "target_column": target_col,
        "prediction_column": prediction_col,
        "cv_prediction_column": validation_prediction_col,
        "residual_column": residual_col,
        "cv_fold_column": validation_fold_col,
        "validation_role_column": validation_role_col,
        "coordinate_columns": coordinate_columns,
        "time_column": time_column,
        "feature_semantics": feature_semantics,
        "gcp_ready": bool(model_type == "regression" and validation_method != "random" and coordinate_columns),
    }
    diagnostics = {
        "target_col": target_col,
        "features": feature_cols,
        "numeric_features": numeric_cols,
        "categorical_features": categorical_cols,
        "split": split_info,
        "sample_count": int(len(work)),
        "task_mode": task_mode,
        "model_type": model_type,
        "top_features": importance_df.head(10).to_dict(orient="records"),
        "tuning": tuning_info,
        "shap": shap_info,
        "modeling_profile": modeling_profile,
        "modeling_advisor": modeling_advisor,
        "feature_semantics": feature_semantics,
        "method_metadata": method_metadata,
        "limitations": limitations,
    }
    diagnostics.update(extra_diagnostics or {})
    summary_path.write_text(json.dumps({"metrics": _json_safe(metrics), "diagnostics": _json_safe(diagnostics)}, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = [
        result_artifact,
        _artifact(Path(manager.get(metrics_dataset).path), "metrics", f"{output_name}_metrics.csv"),
        _artifact(Path(manager.get(importance_dataset).path), "feature_importance", f"{output_name}_feature_importance.csv"),
        _artifact(model_path, "model", f"{output_name}_model.joblib"),
        _artifact(summary_path, "summary", f"{output_name}_summary.json"),
    ]
    task_id = f"generic_xgboost_workflow_{uuid4().hex[:10]}"
    model_result_id = generate_model_result_id("generic_xgboost", output_name)
    registered = manager.register_model_result(
        model_result_id=model_result_id,
        task_id=task_id,
        dataset_id=result_dataset,
        model_name="generic_xgboost",
        output_prefix=output_name,
        result_dataset=result_dataset,
        metrics_dataset=metrics_dataset,
        metrics_path=str(Path(manager.get(metrics_dataset).path)),
        artifact_ids=[],
        artifacts=artifacts,
        metrics=_json_safe(metrics),
        diagnostics=_json_safe(diagnostics),
    )
    outputs = {
        "model_result_id": registered["model_result_id"],
        "model_type": model_type,
        "task_mode": task_mode,
        "result_dataset": result_dataset,
        "prediction_column": prediction_col,
        "target_column": target_col,
        "cv_prediction_column": validation_prediction_col,
        "residual_column": residual_col,
        "cv_fold_column": validation_fold_col,
        "validation_role_column": validation_role_col,
        "validation_method": validation_method,
        "coordinate_columns": coordinate_columns,
        "time_column": time_column,
        "feature_semantics": feature_semantics,
        "gcp_ready": method_metadata["gcp_ready"],
        "metrics": _json_safe(metrics),
        "metrics_dataset": metrics_dataset,
        "importance_dataset": importance_dataset,
        "map_layer_id": _map_layer_id(result_dataset) if gdf is not None else "",
        "generated_files": [str(Path(item["path"])) for item in artifacts],
    }
    return tool_result_ok(
        "generic_xgboost_workflow",
        task_id=task_id,
        inputs=inputs,
        outputs=outputs,
        artifacts=artifacts,
        summary=f"通用 XGBoost {model_type} 已完成，目标变量 {target_col}，样本量 {len(work)}。",
        diagnostics=_json_safe(diagnostics),
    )


def run_generic_xgboost_workflow(
    manager: DataManager,
    *,
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
    lon_col: str = "",
    lat_col: str = "",
    date_col: str = "",
    group_col: str = "",
    split_method: str = "auto",
    test_size: float = 0.2,
    random_state: int = 42,
    auto_tune: bool = False,
    tuning_budget: str = "small",
    enable_shap: bool = False,
    enable_modeling_advisor: bool | None = None,
    modeling_advisor_client: Any | None = None,
    max_training_samples: int = 200000,
    max_prediction_pixels: int = 5000000,
    raster_resampling: str = "bilinear",
    categorical_strategy: str = "onehot",
) -> ToolResult:
    inputs = locals().copy()
    inputs.pop("manager", None)
    blocked = _blocked_sensitive(inputs)
    if blocked:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="SENSITIVE_PATH_BLOCKED",
            error_title="Sensitive path blocked",
            user_message="请求包含敏感路径或文件名，已拒绝读取。",
            diagnostics={"blocked_input": blocked},
        )
    if XGBRegressor is None or XGBClassifier is None:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="XGBOOST_UNAVAILABLE",
            error_title="XGBoost is not installed",
            user_message="当前环境缺少 xgboost，无法训练模型。",
        )
    if not target_col and not target_raster_name:
        return tool_result_error(
            "generic_xgboost_workflow",
            inputs=inputs,
            error_code="TARGET_REQUIRED",
            error_title="Target variable is required",
            user_message="请指定 target_col 或 target_raster_name。",
            diagnostics={"required_inputs": ["target"], "dataset_name": dataset_name, "sample_dataset_name": sample_dataset_name},
            next_actions=["说明要预测的目标字段，例如 target_col='yield'。"],
        )
    output = _safe_name(output_name or f"generic_xgb_{target_col or target_raster_name}")
    mode_norm = str(mode or "auto").lower()
    raster_list = parse_name_list(raster_names)
    feature_list = parse_name_list(feature_cols)
    try:
        if mode_norm == "raster_stack" or (mode_norm == "auto" and raster_list and target_raster_name):
            stack = build_raster_stack(
                manager,
                raster_list,
                target_raster_name=target_raster_name,
                raster_resampling=raster_resampling,
                max_prediction_pixels=max_prediction_pixels,
            )
            x, y, stack_diag = stack_training_frame(stack, max_training_samples=max_training_samples, random_state=random_state)
            df = pd.DataFrame(x, columns=stack.feature_names)
            df["__target__"] = y
            modeling_profile = build_modeling_profile(df, dataset_name=output, data_type="raster_stack")
            result = _fit_table_model(
                manager,
                df=df,
                gdf=None,
                target_col="__target__",
                feature_cols=stack.feature_names,
                output_name=f"{output}_samples",
                task_mode="raster_stack",
                task_type=task_type,
                group_col="",
                date_col="",
                lon_col="",
                lat_col="",
                split_method=split_method,
                test_size=test_size,
                random_state=random_state,
                max_training_samples=max_training_samples,
                auto_tune=auto_tune,
                tuning_budget=tuning_budget,
                enable_shap=enable_shap,
                modeling_advisor=_modeling_advisor_status(modeling_profile, enabled=enable_modeling_advisor, client=modeling_advisor_client),
                extra_diagnostics={"raster_stack": stack_diag},
            )
            if not result.ok:
                return result
            model_artifact = next((a for a in result.artifacts if a.get("type") == "model"), None)
            model_bundle = joblib.load(model_artifact["path"]) if model_artifact else None
            pipeline = model_bundle["pipeline"]
            rows, cols = np.where(stack.valid_mask)
            pred_frame = pd.DataFrame(stack.stack[:, rows, cols].T, columns=stack.feature_names)
            pred = pipeline.predict(pred_frame)
            prediction_path = manager.derived_dir / f"{output}_prediction.tif"
            write_prediction_raster(prediction_path, stack, pred)
            raster_dataset = manager.put_raster_path(
                output,
                prediction_path,
                meta={
                    "crs": str(stack.crs) if stack.crs else "",
                    "width": int(stack.profile["width"]),
                    "height": int(stack.profile["height"]),
                    "source_tool": "generic_xgboost_workflow",
                    "layer_kind": "prediction",
                    "map_ready": True,
                    "map_layer_id": _map_layer_id(output),
                },
            )
            raster_artifact = _artifact(prediction_path, "raster", f"{output}_prediction.tif", dataset_name=raster_dataset, meta={"layer_kind": "prediction"})
            manager.register_artifact(**raster_artifact)
            result.outputs.update({"result_dataset": raster_dataset, "map_layer_id": _map_layer_id(raster_dataset)})
            result.artifacts.insert(0, raster_artifact)
            result.diagnostics["features"] = stack.feature_names
            return result
        if mode_norm == "sample_raster" or (mode_norm == "auto" and raster_list and (sample_dataset_name or dataset_name)):
            sample_name = sample_dataset_name or dataset_name
            sample_gdf, extracted_features, spatial_diag = extract_raster_features(manager, sample_name, raster_list, x_col=x_col, y_col=y_col)
            features = feature_list or extracted_features
            sample_df = pd.DataFrame(sample_gdf.drop(columns=["geometry"], errors="ignore"))
            modeling_profile = build_modeling_profile(sample_df, dataset_name=sample_name, data_type="vector")
            return _fit_table_model(
                manager,
                df=sample_df,
                gdf=sample_gdf,
                target_col=target_col,
                feature_cols=features,
                output_name=output,
                task_mode="sample_raster",
                task_type=task_type,
                group_col=group_col,
                date_col=date_col,
                lon_col=lon_col or x_col,
                lat_col=lat_col or y_col,
                split_method=split_method,
                test_size=test_size,
                random_state=random_state,
                max_training_samples=max_training_samples,
                auto_tune=auto_tune,
                tuning_budget=tuning_budget,
                enable_shap=enable_shap,
                modeling_advisor=_modeling_advisor_status(modeling_profile, enabled=enable_modeling_advisor, client=modeling_advisor_client),
                extra_diagnostics=spatial_diag,
            )
        if not dataset_name:
            return tool_result_error(
                "generic_xgboost_workflow",
                inputs=inputs,
                error_code="DATASET_REQUIRED",
                error_title="Dataset is required",
                user_message="请提供 dataset_name。",
                diagnostics={"required_inputs": ["dataset_name"]},
            )
        df, gdf, task_mode = _dataframe_from_dataset(manager, dataset_name)
        modeling_profile = build_modeling_profile(df, dataset_name=dataset_name, data_type="vector" if gdf is not None else "table")
        return _fit_table_model(
            manager,
            df=df,
            gdf=gdf,
            target_col=target_col,
            feature_cols=feature_list,
            output_name=output,
            task_mode=task_mode,
            task_type=task_type,
            group_col=group_col,
            date_col=date_col,
            lon_col=lon_col or x_col,
            lat_col=lat_col or y_col,
            split_method=split_method,
            test_size=test_size,
            random_state=random_state,
            max_training_samples=max_training_samples,
            auto_tune=auto_tune,
            tuning_budget=tuning_budget,
            enable_shap=enable_shap,
            modeling_advisor=_modeling_advisor_status(modeling_profile, enabled=enable_modeling_advisor, client=modeling_advisor_client),
        )
    except RuntimeError as exc:
        text = str(exc)
        if text.startswith("RASTER_TOO_LARGE:"):
            _, pixels, limit = text.split(":")
            return tool_result_error(
                "generic_xgboost_workflow",
                inputs=inputs,
                error_code="RASTER_TOO_LARGE",
                error_title="Raster is too large",
                user_message="栅格像元数超过上限，请裁剪或降采样后再建模。",
                diagnostics={"pixels": int(pixels), "max_prediction_pixels": int(limit)},
            )
        if text == "XGBOOST_UNAVAILABLE":
            return tool_result_error("generic_xgboost_workflow", inputs=inputs, error_code="XGBOOST_UNAVAILABLE", user_message="当前环境缺少 xgboost。")
        raise
