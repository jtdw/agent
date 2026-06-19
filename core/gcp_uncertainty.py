from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "gcp").strip())
    return stem.strip("._") or "gcp"


def conformal_calibrate(scores: Any, alpha: float) -> float:
    if not 0 < float(alpha) < 1:
        raise ValueError("alpha must be between 0 and 1")
    values = pd.to_numeric(pd.Series(scores), errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) == 0:
        raise ValueError("calibration scores are empty")
    quantile_level = min(1.0, math.ceil((len(values) + 1) * (1 - float(alpha))) / len(values))
    return float(np.quantile(values, quantile_level, method="higher"))


def _weighted_quantile(values: np.ndarray, quantile: float, sample_weight: np.ndarray | None = None) -> float:
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(values)
    values = values[mask]
    if values.size == 0:
        return float("nan")
    if sample_weight is None:
        return float(np.quantile(values, quantile, method="higher"))
    weights = np.asarray(sample_weight, dtype=float)[mask]
    valid = np.isfinite(weights) & (weights > 0)
    values = values[valid]
    weights = weights[valid]
    if values.size == 0 or float(weights.sum()) <= 0:
        return float(np.quantile(np.asarray(values if values.size else [0.0]), quantile, method="higher"))
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = float(quantile) * float(cumulative[-1])
    index = int(np.searchsorted(cumulative, cutoff, side="left"))
    return float(sorted_values[min(index, len(sorted_values) - 1)])


def _kernel_weights(distances: np.ndarray, bandwidth: float) -> np.ndarray:
    bw = float(bandwidth) if float(bandwidth or 0) > 0 else 1.0
    scaled = np.asarray(distances, dtype=float) / bw
    return np.exp(-0.5 * np.square(scaled))


def _auto_bandwidth(coords: np.ndarray) -> float:
    if len(coords) < 2:
        return 1.0
    sample = coords[: min(len(coords), 200)]
    distances: list[float] = []
    for i in range(len(sample)):
        diff = sample - sample[i]
        d = np.sqrt(np.sum(np.square(diff), axis=1))
        distances.extend(float(v) for v in d if v > 0)
    if not distances:
        return 1.0
    return max(float(np.median(distances)), 1e-9)


def _level_from_width(widths: pd.Series) -> pd.Series:
    values = pd.to_numeric(widths, errors="coerce")
    if values.dropna().nunique() < 3:
        return pd.Series(["medium" if pd.notna(v) else "" for v in values], index=values.index)
    low = values.quantile(1 / 3)
    high = values.quantile(2 / 3)
    return pd.Series(
        np.where(values <= low, "low", np.where(values >= high, "high", "medium")),
        index=values.index,
    )


def compute_uncertainty_metrics(
    predictions: pd.DataFrame,
    *,
    observed_col: str,
    lower_col: str,
    upper_col: str,
    pred_col: str,
    alpha: float,
    method: str,
    spatial_weighting: bool,
    bandwidth: float | None,
    fold_col: str = "",
) -> dict[str, Any]:
    work = predictions.copy()
    obs = pd.to_numeric(work.get(observed_col), errors="coerce")
    lower = pd.to_numeric(work.get(lower_col), errors="coerce")
    upper = pd.to_numeric(work.get(upper_col), errors="coerce")
    pred = pd.to_numeric(work.get(pred_col), errors="coerce")
    width = upper - lower
    valid_interval = lower.notna() & upper.notna()
    valid_obs = valid_interval & obs.notna()
    covered = (obs >= lower) & (obs <= upper)
    empirical = float(covered.loc[valid_obs].mean()) if bool(valid_obs.any()) else None
    penalty = pd.Series(0.0, index=work.index)
    penalty = penalty.mask(obs < lower, (lower - obs) * (2.0 / float(alpha)))
    penalty = penalty.mask(obs > upper, (obs - upper) * (2.0 / float(alpha)))
    interval_score = float((width + penalty).loc[valid_obs].mean()) if bool(valid_obs.any()) else None
    residual = (obs - pred).abs()
    coverage_by_block: dict[str, float] = {}
    width_by_block: dict[str, float] = {}
    if fold_col and fold_col in work.columns:
        for key, group in work.loc[valid_interval].groupby(fold_col):
            key_text = str(key)
            width_by_block[key_text] = float((pd.to_numeric(group[upper_col], errors="coerce") - pd.to_numeric(group[lower_col], errors="coerce")).mean())
            if observed_col in group.columns:
                block_obs = pd.to_numeric(group[observed_col], errors="coerce")
                block_lower = pd.to_numeric(group[lower_col], errors="coerce")
                block_upper = pd.to_numeric(group[upper_col], errors="coerce")
                block_valid = block_obs.notna()
                if bool(block_valid.any()):
                    coverage_by_block[key_text] = float(((block_obs >= block_lower) & (block_obs <= block_upper)).loc[block_valid].mean())
    mean_width = float(width.loc[valid_interval].mean()) if bool(valid_interval.any()) else None
    median_width = float(width.loc[valid_interval].median()) if bool(valid_interval.any()) else None
    width_std = float(width.loc[valid_interval].std(ddof=1)) if int(valid_interval.sum()) > 1 else 0.0
    return {
        "method": method,
        "alpha": float(alpha),
        "target_coverage": float(1 - alpha),
        "empirical_coverage": empirical,
        "mean_interval_width": mean_width,
        "median_interval_width": median_width,
        "interval_width_std": width_std,
        "interval_score": interval_score,
        "mean_absolute_residual": float(residual.loc[valid_obs].mean()) if bool(valid_obs.any()) else None,
        "spatial_weighting": bool(spatial_weighting),
        "bandwidth": float(bandwidth) if bandwidth is not None else None,
        "coverage_by_block": coverage_by_block,
        "width_by_block": width_by_block,
        "PICP": empirical,
        "MPIW": mean_width,
        "NMPIW": float(mean_width / (obs.max() - obs.min())) if mean_width is not None and obs.notna().any() and float(obs.max() - obs.min()) != 0 else None,
        "QCP": None,
        "IS": interval_score,
        "n_target": int(valid_interval.sum()),
    }


def _save_figure(fig: Any, path: Path, dpi: int = 150) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")


def generate_gcp_visualizations(
    predictions: pd.DataFrame,
    *,
    output_name: str,
    output_dir: str | Path,
    observed_col: str,
    predicted_col: str,
    lon_col: str = "",
    lat_col: str = "",
    metrics: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    prefix = _safe_stem(output_name)
    images: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    warnings: list[str] = []

    def add(name: str, path: Path, title: str) -> None:
        images.append({"name": name, "path": str(path), "title": title, "mime_type": "image/png"})

    width = pd.to_numeric(predictions["interval_width"], errors="coerce")
    lower = pd.to_numeric(predictions["prediction_interval_lower"], errors="coerce")
    upper = pd.to_numeric(predictions["prediction_interval_upper"], errors="coerce")
    pred = pd.to_numeric(predictions[predicted_col], errors="coerce")
    obs = pd.to_numeric(predictions[observed_col], errors="coerce") if observed_col in predictions.columns else pd.Series(np.nan, index=predictions.index)
    valid = pred.notna() & lower.notna() & upper.notna()

    if lon_col and lat_col and lon_col in predictions.columns and lat_col in predictions.columns:
        lon = pd.to_numeric(predictions[lon_col], errors="coerce")
        lat = pd.to_numeric(predictions[lat_col], errors="coerce")
        spatial = valid & lon.notna() & lat.notna() & width.notna()
        if bool(spatial.any()):
            fig, ax = plt.subplots(figsize=(7, 5))
            sc = ax.scatter(lon.loc[spatial], lat.loc[spatial], c=width.loc[spatial], cmap="magma", s=38, alpha=0.86)
            ax.set_title("GCP Uncertainty / Interval Width")
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            fig.colorbar(sc, ax=ax, label="Interval width")
            path = output_path / f"{prefix}_gcp_interval_width_spatial.png"
            _save_figure(fig, path)
            plt.close(fig)
            add("interval_width_spatial", path, "GCP interval width spatial distribution")
        else:
            skipped.append({"name": "interval_width_spatial", "reason": "no valid coordinate rows"})
    else:
        skipped.append({"name": "interval_width_spatial", "reason": "longitude/latitude columns unavailable"})

    try:
        ordered = predictions.loc[valid].copy().reset_index(drop=True)
        if ordered.empty:
            raise ValueError("no valid interval rows")
        x = np.arange(len(ordered))
        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.fill_between(x, ordered["prediction_interval_lower"], ordered["prediction_interval_upper"], color="#93c5fd", alpha=0.45, label="interval")
        ax.plot(x, ordered[predicted_col], color="#2563eb", linewidth=1.4, label="prediction")
        if observed_col in ordered.columns:
            ax.scatter(x, ordered[observed_col], color="#111827", s=16, label="actual")
        ax.set_title("GCP Prediction Intervals")
        ax.set_xlabel("Sample index")
        ax.set_ylabel("Value")
        ax.legend()
        path = output_path / f"{prefix}_gcp_prediction_intervals.png"
        _save_figure(fig, path)
        plt.close(fig)
        add("prediction_intervals", path, "GCP prediction intervals")
    except Exception as exc:
        warnings.append(str(exc))
        skipped.append({"name": "prediction_intervals", "reason": str(exc)})

    try:
        covered = predictions.get("covered")
        if covered is None:
            raise ValueError("coverage column unavailable")
        covered_bool = pd.to_numeric(covered, errors="coerce") == 1
        fig, ax = plt.subplots(figsize=(7, 4.8))
        ax.scatter(pred.loc[valid & covered_bool], obs.loc[valid & covered_bool], color="#16a34a", s=28, label="covered")
        ax.scatter(pred.loc[valid & ~covered_bool], obs.loc[valid & ~covered_bool], color="#dc2626", s=34, label="not covered")
        coverage = metrics.get("empirical_coverage") if metrics else None
        ax.set_title(f"GCP Coverage ({coverage:.3f})" if isinstance(coverage, (int, float)) else "GCP Coverage")
        ax.set_xlabel("Prediction")
        ax.set_ylabel("Actual")
        ax.legend()
        path = output_path / f"{prefix}_gcp_coverage.png"
        _save_figure(fig, path)
        plt.close(fig)
        add("coverage", path, "GCP coverage")
    except Exception as exc:
        warnings.append(str(exc))
        skipped.append({"name": "coverage", "reason": str(exc)})

    try:
        values = width.loc[width.notna()]
        if values.empty:
            raise ValueError("interval width is empty")
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.hist(values, bins=min(20, max(5, int(np.sqrt(len(values))))), color="#f59e0b", edgecolor="white", alpha=0.82)
        ax.axvline(values.mean(), color="#2563eb", linestyle="--", label=f"mean={values.mean():.3f}")
        ax.axvline(values.median(), color="#7c3aed", linestyle=":", label=f"median={values.median():.3f}")
        ax.set_title("GCP Interval Width Distribution")
        ax.set_xlabel("Interval width")
        ax.set_ylabel("Count")
        ax.legend()
        path = output_path / f"{prefix}_gcp_interval_width_distribution.png"
        _save_figure(fig, path)
        plt.close(fig)
        add("interval_width_distribution", path, "GCP interval width distribution")
    except Exception as exc:
        warnings.append(str(exc))
        skipped.append({"name": "interval_width_distribution", "reason": str(exc)})

    try:
        abs_residual = (obs - pred).abs()
        mask = valid & abs_residual.notna() & width.notna()
        if not bool(mask.any()):
            raise ValueError("no valid residual/width rows")
        fig, ax = plt.subplots(figsize=(7, 4.8))
        ax.scatter(abs_residual.loc[mask], width.loc[mask], color="#0891b2", s=30, alpha=0.82)
        ax.set_title("Absolute Residual vs Interval Width")
        ax.set_xlabel("Absolute residual")
        ax.set_ylabel("Interval width")
        path = output_path / f"{prefix}_gcp_residual_vs_width.png"
        _save_figure(fig, path)
        plt.close(fig)
        add("residual_vs_width", path, "GCP residual vs interval width")
    except Exception as exc:
        warnings.append(str(exc))
        skipped.append({"name": "residual_vs_width", "reason": str(exc)})

    return images, skipped, warnings


def _build_report(metrics: dict[str, Any], warnings: list[str]) -> str:
    lines = [
        "# GCP Uncertainty Analysis Report",
        "",
        f"- Method: {metrics.get('method')}",
        f"- Target coverage: {metrics.get('target_coverage')}",
        f"- Empirical coverage: {metrics.get('empirical_coverage')}",
        f"- Mean interval width: {metrics.get('mean_interval_width')}",
        f"- Median interval width: {metrics.get('median_interval_width')}",
        f"- Interval score: {metrics.get('interval_score')}",
        "",
        "## Interpretation",
        "The prediction interval summarizes uncertainty around point predictions. Coverage close to the target means the interval is reliable; smaller width means tighter predictions when coverage remains acceptable.",
        "",
        "## Limitations",
    ]
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- No major limitations were detected by the automated GCP step.")
    lines.extend(["", "## Next Steps", "- Inspect high uncertainty samples or regions.", "- Compare interval reliability with point prediction accuracy."])
    return "\n".join(lines) + "\n"


def run_gcp_uncertainty_analysis(
    *,
    data: pd.DataFrame,
    observed_col: str,
    predicted_col: str,
    output_name: str,
    output_dir: str | Path,
    target_data: pd.DataFrame | None = None,
    lon_col: str = "",
    lat_col: str = "",
    alpha: float = 0.1,
    calibration_ratio: float = 0.3,
    calibration_selection: str = "latest",
    spatial_weighting: bool = True,
    spatial_bandwidth: float = 0.0,
    fold_col: str = "",
    cv_available_col: str = "",
    date_col: str = "",
) -> dict[str, Any]:
    if not 0 < float(alpha) < 1:
        raise ValueError("alpha must be between 0 and 1")
    if predicted_col not in data.columns:
        raise ValueError(f"prediction column not found: {predicted_col}")
    if observed_col not in data.columns:
        raise ValueError(f"observed column not found: {observed_col}")

    cal_df = data.copy()
    target_df = target_data.copy() if target_data is not None else data.copy()
    if predicted_col not in target_df.columns:
        raise ValueError(f"target prediction column not found: {predicted_col}")

    cal_obs = pd.to_numeric(cal_df[observed_col], errors="coerce")
    cal_pred = pd.to_numeric(cal_df[predicted_col], errors="coerce")
    base_valid = cal_obs.notna() & cal_pred.notna()
    warnings: list[str] = []

    if cv_available_col and cv_available_col in cal_df.columns:
        cal_mask = base_valid & cal_df[cv_available_col].astype(bool)
        target_mask = cal_mask.reindex(target_df.index, fill_value=False) if target_data is None else pd.Series(True, index=target_df.index)
    else:
        valid_index = cal_df.index[base_valid]
        if date_col and date_col in cal_df.columns:
            valid_index = cal_df.loc[valid_index].sort_values(date_col).index
        take_n = min(len(valid_index), max(5, int(len(valid_index) * float(calibration_ratio))))
        if calibration_selection == "earliest":
            chosen = valid_index[:take_n]
        elif calibration_selection == "random":
            chosen = pd.Index(np.random.default_rng(42).choice(valid_index.to_numpy(), size=take_n, replace=False)) if take_n else pd.Index([])
        else:
            chosen = valid_index[-take_n:]
        cal_mask = cal_df.index.isin(chosen) & base_valid
        target_mask = pd.Series(True, index=target_df.index)

    cal_scores = (cal_obs - cal_pred).abs().loc[cal_mask]
    if len(cal_scores.dropna()) < 5:
        raise ValueError("at least 5 calibration samples are required")
    q_hat = conformal_calibrate(cal_scores, float(alpha))

    predictions = target_df.copy()
    pred = pd.to_numeric(predictions[predicted_col], errors="coerce")
    valid_target = pd.Series(target_mask, index=predictions.index) & pred.notna()
    local_q = pd.Series(float(q_hat), index=predictions.index, dtype=float)
    method = "split_conformal"
    bandwidth_used: float | None = None

    has_coords = bool(lon_col and lat_col and lon_col in cal_df.columns and lat_col in cal_df.columns and lon_col in predictions.columns and lat_col in predictions.columns)
    if spatial_weighting and has_coords:
        cal_xy_frame = pd.DataFrame({"x": pd.to_numeric(cal_df[lon_col], errors="coerce"), "y": pd.to_numeric(cal_df[lat_col], errors="coerce")})
        target_xy_frame = pd.DataFrame({"x": pd.to_numeric(predictions[lon_col], errors="coerce"), "y": pd.to_numeric(predictions[lat_col], errors="coerce")})
        spatial_cal_mask = pd.Series(cal_mask, index=cal_df.index) & cal_xy_frame.notna().all(axis=1)
        spatial_target_mask = valid_target & target_xy_frame.notna().all(axis=1)
        if bool(spatial_cal_mask.any()) and bool(spatial_target_mask.any()):
            cal_xy = cal_xy_frame.loc[spatial_cal_mask].to_numpy(dtype=float)
            scores = (pd.to_numeric(cal_df.loc[spatial_cal_mask, observed_col], errors="coerce") - pd.to_numeric(cal_df.loc[spatial_cal_mask, predicted_col], errors="coerce")).abs().to_numpy(dtype=float)
            bandwidth_used = float(spatial_bandwidth) if float(spatial_bandwidth or 0) > 0 else _auto_bandwidth(cal_xy)
            quantile_level = min(1.0, math.ceil((len(scores) + 1) * (1 - float(alpha))) / len(scores))
            for idx, row in target_xy_frame.loc[spatial_target_mask].iterrows():
                xy = row.to_numpy(dtype=float)
                distances = np.sqrt(np.sum(np.square(cal_xy - xy), axis=1))
                weights = _kernel_weights(distances, bandwidth_used)
                local_q.loc[idx] = _weighted_quantile(scores, quantile_level, weights)
            method = "gcp"
        else:
            warnings.append("spatial weighting requested but valid coordinate rows were insufficient; used split conformal")
    elif spatial_weighting:
        warnings.append("spatial weighting requested but lon/lat were unavailable; used split conformal")

    predictions["prediction_interval_lower"] = np.nan
    predictions["prediction_interval_upper"] = np.nan
    predictions.loc[valid_target, "prediction_interval_lower"] = pred.loc[valid_target] - local_q.loc[valid_target]
    predictions.loc[valid_target, "prediction_interval_upper"] = pred.loc[valid_target] + local_q.loc[valid_target]
    predictions["interval_width"] = predictions["prediction_interval_upper"] - predictions["prediction_interval_lower"]
    obs_target = pd.to_numeric(predictions[observed_col], errors="coerce") if observed_col in predictions.columns else pd.Series(np.nan, index=predictions.index)
    predictions["nonconformity_score"] = (obs_target - pred).abs()
    predictions["covered"] = ((obs_target >= predictions["prediction_interval_lower"]) & (obs_target <= predictions["prediction_interval_upper"])).astype(float)
    predictions.loc[obs_target.isna(), "covered"] = np.nan
    predictions["uncertainty_level"] = _level_from_width(predictions["interval_width"])

    metrics = compute_uncertainty_metrics(
        predictions,
        observed_col=observed_col,
        lower_col="prediction_interval_lower",
        upper_col="prediction_interval_upper",
        pred_col=predicted_col,
        alpha=float(alpha),
        method=method,
        spatial_weighting=spatial_weighting and method == "gcp",
        bandwidth=bandwidth_used,
        fold_col=fold_col,
    )
    metrics["q_hat"] = float(q_hat)
    metrics["n_calibration"] = int(pd.Series(cal_mask, index=cal_df.index).sum())

    images, skipped_images, image_warnings = generate_gcp_visualizations(
        predictions,
        output_name=output_name,
        output_dir=output_dir,
        observed_col=observed_col,
        predicted_col=predicted_col,
        lon_col=lon_col,
        lat_col=lat_col,
        metrics=metrics,
    )
    warnings.extend(image_warnings)
    report = _build_report(metrics, warnings + [f"skipped {item['name']}: {item['reason']}" for item in skipped_images])
    return {
        "predictions": predictions,
        "metrics": metrics,
        "images": images,
        "skipped_images": skipped_images,
        "warnings": warnings,
        "report_markdown": report,
    }
