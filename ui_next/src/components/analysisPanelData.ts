import type { ModelMetricDatum } from './ModelMetricChart';
import type { ResultPanel } from '@/lib/api';

type AnyRecord = Record<string, unknown>;

export type AnalysisMetricRow = {
  model_result_id?: string;
  model?: string;
  predicted?: string;
  R?: number | string | null;
  R2?: number | string | null;
  RMSE?: number | string | null;
  MAE?: number | string | null;
  NSE?: number | string | null;
  Accuracy?: number | string | null;
  Precision?: number | string | null;
  Recall?: number | string | null;
  F1?: number | string | null;
  AUC?: number | string | null;
  [key: string]: unknown;
};

export type AnalysisDownload = {
  artifactId: string;
  label: string;
  url: string;
  kind: 'report' | 'chart' | 'artifact';
};

export type AnalysisPanelView = {
  hasResults: boolean;
  title: string;
  status: string;
  metricsDataset: string;
  bestModel?: ModelMetricDatum;
  cards: Array<{ label: string; value: string }>;
  chartData: ModelMetricDatum[];
  downloads: AnalysisDownload[];
  featureImportance: Array<{ feature: string; importance: number | null }>;
  recommendations: string[];
  steps: Array<{ name: string; status: string; summary: string }>;
};

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === 'object' ? value as AnyRecord : {};
}

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value.filter((item): item is AnyRecord => Boolean(item) && typeof item === 'object') : [];
}

function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function fmt(value: number | null) {
  return value === null ? '--' : value.toFixed(3);
}

function modelName(row: AnalysisMetricRow) {
  return String(row.model || row.predicted || '模型');
}

function metricRows(dashboard: unknown): AnalysisMetricRow[] {
  const root = asRecord(dashboard);
  const analysis = asRecord(root.analysis);
  const modelResults = asArray(root.model_results);
  const idsByName = new Map<string, string>();
  for (const result of modelResults) {
    const id = String(result.model_result_id || '');
    const name = String(result.model || result.output_prefix || '');
    if (id && name) idsByName.set(name, id);
  }
  const rows = asArray(analysis.metric_rows);
  if (rows.length) {
    return rows.map((row) => {
      const name = modelName(row as AnalysisMetricRow);
      return { ...row, model_result_id: String(row.model_result_id || idsByName.get(name) || '') };
    }) as AnalysisMetricRow[];
  }
  return modelResults.map((result) => ({
    model_result_id: String(result.model_result_id || ''),
    model: String(result.model || result.output_prefix || '模型'),
    ...asRecord(result.metrics)
  })) as AnalysisMetricRow[];
}

function metricDataset(dashboard: unknown) {
  const root = asRecord(dashboard);
  const analysis = asRecord(root.analysis);
  const latest = asRecord(root.latest_pipeline);
  const summary = asRecord(latest.summary);
  const reports = asRecord(summary.reports);
  const firstModel = asRecord(asArray(root.model_results)[0]);
  return String(analysis.metrics_dataset || reports.metrics_dataset || firstModel.metrics_dataset || '');
}

function chartRows(rows: AnalysisMetricRow[]): ModelMetricDatum[] {
  return rows
    .map((row) => ({
      name: modelName(row),
      modelResultId: String(row.model_result_id || ''),
      r: num(row.R2) ?? num(row.R) ?? num(row.Accuracy) ?? 0,
      rmse: num(row.RMSE) ?? 0,
      nse: num(row.NSE) ?? num(row.F1)
    }))
    .filter((row) => row.r || row.rmse || row.nse !== null);
}

function bestByRmse(rows: ModelMetricDatum[]) {
  const valid = rows.filter((row) => Number.isFinite(row.rmse) && row.rmse > 0);
  if (valid.length) return valid.reduce((best, row) => row.rmse < best.rmse ? row : best);
  return rows.filter((row) => Number.isFinite(row.r)).reduce((best, row) => row.r > best.r ? row : best, rows[0]);
}

function downloads(dashboard: unknown, resultPanel?: ResultPanel | null): AnalysisDownload[] {
  if (resultPanel?.files?.length) {
    return resultPanel.files
      .map((item) => {
        const url = String(item.download_url || '');
        if (!url) return null;
        const name = String(item.label || item.path || '成果文件');
        const lower = name.toLowerCase();
        const kind: AnalysisDownload['kind'] = lower.match(/\.(png|jpg|jpeg|webp|svg)$/) ? 'chart' : lower.match(/\.(md|txt|docx|pdf|csv|xlsx)$/) ? 'report' : 'artifact';
        return { artifactId: String(item.artifact_id || ''), label: name, url, kind };
      })
      .filter((item): item is AnalysisDownload => Boolean(item))
      .slice(0, 12);
  }
  const root = asRecord(dashboard);
  const modelArtifacts = asArray(root.model_results).flatMap((result) => asArray(result.artifacts));
  const artifacts = [...modelArtifacts, ...asArray(root.artifacts)];
  const seen = new Set<string>();
  return artifacts
    .map((item) => {
      const url = String(item.download_url || '');
      if (!url || seen.has(url)) return null;
      seen.add(url);
      const name = String(item.label || item.name || item.path || '成果文件');
      const lower = name.toLowerCase();
      const kind: AnalysisDownload['kind'] = lower.match(/\.(png|jpg|jpeg|webp|svg)$/) ? 'chart' : lower.match(/\.(md|txt|docx|pdf|csv|xlsx)$/) ? 'report' : 'artifact';
      return { artifactId: String(item.artifact_id || item.id || ''), label: name, url, kind };
    })
    .filter((item): item is AnalysisDownload => Boolean(item))
    .slice(0, 8);
}

function pipelineSteps(dashboard: unknown) {
  const latest = asRecord(asRecord(dashboard).latest_pipeline);
  return asArray(latest.steps).map((step) => ({
    name: String(step.step_name || step.name || '步骤'),
    status: String(step.status || ''),
    summary: String(step.output_summary || step.input_summary || '')
  })).slice(0, 8);
}

function recommendations(dashboard: unknown, resultPanel?: ResultPanel | null): string[] {
  if (resultPanel?.recommendations?.length) return resultPanel.recommendations.map(String).filter(Boolean).slice(0, 5);
  return asArray(asRecord(dashboard).model_results)
    .flatMap((result) => Array.isArray(result.recommendations) ? result.recommendations.map(String) : [])
    .filter(Boolean)
    .slice(0, 5);
}

function metricCards(row?: AnalysisMetricRow): Array<{ label: string; value: string }> {
  if (!row) return [];
  const classification = num(row.Accuracy) !== null || num(row.F1) !== null;
  if (classification) {
    return [
      { label: 'Accuracy', value: fmt(num(row.Accuracy)) },
      { label: 'F1', value: fmt(num(row.F1)) },
      { label: 'AUC', value: fmt(num(row.AUC)) }
    ];
  }
  if (num(row.R2) === null && num(row.MAE) === null && num(row.R) !== null) {
    return [
      { label: 'R', value: fmt(num(row.R)) },
      { label: 'RMSE', value: fmt(num(row.RMSE)) },
      { label: 'NSE', value: fmt(num(row.NSE)) }
    ];
  }
  return [
    { label: 'R2', value: fmt(num(row.R2) ?? num(row.R)) },
    { label: 'RMSE', value: fmt(num(row.RMSE)) },
    { label: 'MAE', value: fmt(num(row.MAE) ?? num(row.NSE)) }
  ];
}

function featureImportance(dashboard: unknown): Array<{ feature: string; importance: number | null }> {
  const modelResults = asArray(asRecord(dashboard).model_results);
  const latest = modelResults[0];
  const diagnostics = asRecord(latest?.diagnostics);
  const rows = asArray(diagnostics.top_features);
  return rows
    .map((item) => ({
      feature: String(item.feature || item.encoded_feature || ''),
      importance: num(item.importance)
    }))
    .filter((item) => item.feature)
    .slice(0, 8);
}

export function buildAnalysisPanelView(dashboard: unknown, resultPanel?: ResultPanel | null): AnalysisPanelView {
  const root = asRecord(dashboard);
  const latest = asRecord(root.latest_pipeline);
  const rawRows = metricRows(root);
  const rows = chartRows(rawRows);
  const bestModel = rows.length ? bestByRmse(rows) : undefined;
  const bestRawRow = bestModel
    ? rawRows.find((row) => (bestModel.modelResultId ? String(row.model_result_id || '') === bestModel.modelResultId : false) || modelName(row) === bestModel.name)
    : rawRows[0];
  const cards = metricCards(bestRawRow);
  const files = downloads(root, resultPanel);
  const steps = pipelineSteps(root);
  const advice = recommendations(root, resultPanel);
  const importance = featureImportance(root);
  const hasResults = Boolean(resultPanel?.has_results || rows.length || files.length || steps.length || latest.run_id || advice.length || importance.length);
  if (resultPanel?.title) latest.pipeline_name = resultPanel.title;

  return {
    hasResults,
    title: String(latest.pipeline_name || '分析结果'),
    status: String(latest.status || ''),
    metricsDataset: metricDataset(root),
    bestModel,
    cards,
    chartData: rows,
    downloads: files,
    featureImportance: importance,
    recommendations: advice,
    steps
  };
}
