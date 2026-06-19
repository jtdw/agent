from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "model").strip())
    return stem.strip("._") or "model"


def _to_numeric_series(value: Any, *, name: str = "") -> pd.Series:
    series = value if isinstance(value, pd.Series) else pd.Series(value)
    return pd.to_numeric(series, errors="coerce").rename(name or getattr(series, "name", None))


def _metric_value(metrics: dict[str, Any], *names: str) -> float | None:
    normalized = {str(key).lower(): value for key, value in (metrics or {}).items()}
    for name in names:
        value = normalized.get(name.lower())
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _metric_label(metrics: dict[str, Any]) -> str:
    r2 = _metric_value(metrics, "r2", "r_squared", "R2")
    rmse = _metric_value(metrics, "rmse")
    mae = _metric_value(metrics, "mae")
    parts = []
    if r2 is not None:
        parts.append(f"R2={r2:.3f}")
    if rmse is not None:
        parts.append(f"RMSE={rmse:.3f}")
    if mae is not None:
        parts.append(f"MAE={mae:.3f}")
    return " | ".join(parts)


def _save_figure(fig: Any, path: Path, *, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")


def _image_payload(name: str, path: Path, title: str, description: str) -> dict[str, str]:
    return {
        "name": name,
        "path": str(path),
        "title": title,
        "description": description,
        "mime_type": "image/png",
    }


def _append_warning(warnings: list[str], skipped: list[dict[str, str]], name: str, reason: str) -> None:
    warnings.append(f"{name}: {reason}")
    skipped.append({"name": name, "reason": reason})


def _metric_dict(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    if any(key in metrics for key in ("r2", "rmse", "mae", "R2")):
        return metrics
    for key in ("spatial_cv", "overall", "test", "final_model_in_sample", "train"):
        value = metrics.get(key)
        if isinstance(value, dict):
            return value
    for value in metrics.values():
        if isinstance(value, dict):
            return value
    return metrics


def generate_model_visualizations(
    *,
    y_true: Any,
    y_pred: Any,
    residuals: Any,
    feature_importance: pd.DataFrame,
    metrics: dict[str, Any] | None,
    output_name: str,
    output_dir: str | Path,
    lon: Any | None = None,
    lat: Any | None = None,
    dpi: int = 150,
) -> dict[str, Any]:
    """Generate standard model diagnostic PNGs without failing the caller."""

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    prefix = _safe_stem(output_name)
    images: list[dict[str, str]] = []
    skipped_images: list[dict[str, str]] = []
    warnings: list[str] = []
    metric_values = _metric_dict(metrics)

    y_true_series = _to_numeric_series(y_true, name="actual")
    y_pred_series = _to_numeric_series(y_pred, name="prediction")
    residual_series = _to_numeric_series(residuals, name="residual")
    base_mask = y_true_series.notna() & y_pred_series.notna()
    residual_mask = residual_series.notna()

    try:
        importance = feature_importance.copy()
        if not {"feature", "importance"}.issubset(set(importance.columns)):
            raise ValueError("feature_importance must contain feature and importance columns")
        importance["importance"] = pd.to_numeric(importance["importance"], errors="coerce")
        importance = importance.dropna(subset=["feature", "importance"]).sort_values("importance", ascending=True)
        if importance.empty:
            raise ValueError("feature importance table is empty")
        fig, ax = plt.subplots(figsize=(8, max(3.5, 0.4 * len(importance))))
        ax.barh(importance["feature"].astype(str), importance["importance"], color="#2563eb")
        ax.set_xlabel("Importance")
        ax.set_title("XGBoost Feature Importance")
        path = output_path / f"{prefix}_feature_importance.png"
        _save_figure(fig, path, dpi=dpi)
        plt.close(fig)
        images.append(_image_payload("feature_importance", path, "XGBoost Feature Importance", "Feature importance bar chart."))
    except Exception as exc:  # pragma: no cover - exercised through warnings in integration tests
        _append_warning(warnings, skipped_images, "feature_importance", str(exc))

    try:
        if int(base_mask.sum()) < 2:
            raise ValueError("need at least two valid actual/prediction pairs")
        actual = y_true_series.loc[base_mask]
        predicted = y_pred_series.loc[base_mask]
        low = float(min(actual.min(), predicted.min()))
        high = float(max(actual.max(), predicted.max()))
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(actual, predicted, s=30, alpha=0.78, color="#0f766e", edgecolors="white", linewidths=0.5)
        ax.plot([low, high], [low, high], linestyle="--", color="#ef4444", linewidth=1.2, label="1:1")
        ax.set_xlabel("Actual")
        ax.set_ylabel("Predicted")
        label = _metric_label(metric_values)
        ax.set_title("Predicted vs Actual")
        if label:
            ax.text(0.04, 0.96, label, transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "#cbd5e1"})
        ax.legend(loc="lower right")
        path = output_path / f"{prefix}_pred_vs_actual.png"
        _save_figure(fig, path, dpi=dpi)
        plt.close(fig)
        images.append(_image_payload("pred_vs_actual", path, "Predicted vs Actual", "Scatter plot comparing predicted and actual values."))
    except Exception as exc:
        _append_warning(warnings, skipped_images, "pred_vs_actual", str(exc))

    try:
        values = residual_series.loc[residual_mask]
        if values.empty:
            raise ValueError("residual series is empty")
        mean = float(values.mean())
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.hist(values, bins=min(20, max(5, int(np.sqrt(len(values))))), color="#7c3aed", alpha=0.78, edgecolor="white")
        ax.axvline(mean, color="#ef4444", linestyle="--", linewidth=1.2, label=f"mean={mean:.3f}")
        ax.set_xlabel("Residual")
        ax.set_ylabel("Count")
        ax.set_title("Residual Distribution")
        ax.text(0.98, 0.94, f"mean={mean:.3f}\nstd={std:.3f}", transform=ax.transAxes, va="top", ha="right", fontsize=9, bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "#cbd5e1"})
        ax.legend(loc="upper left")
        path = output_path / f"{prefix}_residual_distribution.png"
        _save_figure(fig, path, dpi=dpi)
        plt.close(fig)
        images.append(_image_payload("residual_distribution", path, "Residual Distribution", "Histogram of model residuals."))
    except Exception as exc:
        _append_warning(warnings, skipped_images, "residual_distribution", str(exc))

    lon_series = _to_numeric_series(lon, name="lon") if lon is not None else None
    lat_series = _to_numeric_series(lat, name="lat") if lat is not None else None
    if lon_series is None or lat_series is None:
        _append_warning(warnings, skipped_images, "residual_spatial", "longitude/latitude columns were not provided")
        _append_warning(warnings, skipped_images, "prediction_spatial", "longitude/latitude columns were not provided")
    else:
        try:
            spatial_mask = lon_series.notna() & lat_series.notna() & residual_series.notna()
            if int(spatial_mask.sum()) < 1:
                raise ValueError("no valid coordinate/residual rows")
            fig, ax = plt.subplots(figsize=(7, 5))
            scatter = ax.scatter(lon_series.loc[spatial_mask], lat_series.loc[spatial_mask], c=residual_series.loc[spatial_mask], cmap="coolwarm", s=36, alpha=0.86)
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title("Residual Spatial Distribution")
            fig.colorbar(scatter, ax=ax, label="Residual")
            path = output_path / f"{prefix}_residual_spatial.png"
            _save_figure(fig, path, dpi=dpi)
            plt.close(fig)
            images.append(_image_payload("residual_spatial", path, "Residual Spatial Distribution", "Spatial scatter plot colored by residual."))
        except Exception as exc:
            _append_warning(warnings, skipped_images, "residual_spatial", str(exc))

        try:
            spatial_mask = lon_series.notna() & lat_series.notna() & y_pred_series.notna()
            if int(spatial_mask.sum()) < 1:
                raise ValueError("no valid coordinate/prediction rows")
            fig, ax = plt.subplots(figsize=(7, 5))
            scatter = ax.scatter(lon_series.loc[spatial_mask], lat_series.loc[spatial_mask], c=y_pred_series.loc[spatial_mask], cmap="viridis", s=36, alpha=0.86)
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title("Prediction Spatial Distribution")
            fig.colorbar(scatter, ax=ax, label="Prediction")
            path = output_path / f"{prefix}_prediction_spatial.png"
            _save_figure(fig, path, dpi=dpi)
            plt.close(fig)
            images.append(_image_payload("prediction_spatial", path, "Prediction Spatial Distribution", "Spatial scatter plot colored by prediction."))
        except Exception as exc:
            _append_warning(warnings, skipped_images, "prediction_spatial", str(exc))

    return {"images": images, "skipped_images": skipped_images, "warnings": warnings}
