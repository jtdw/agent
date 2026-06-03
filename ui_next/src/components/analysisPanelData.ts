import type { ModelMetricDatum } from './ModelMetricChart';

type AnyRecord = Record<string, unknown>;

export type AnalysisMetricRow = {
  model?: string;
  predicted?: string;
  R?: number | string | null;
  RMSE?: number | string | null;
  NSE?: number | string | null;
  [key: string]: unknown;
};

export type AnalysisDownload = {
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
  const rows = asArray(analysis.metric_rows);
  return rows as AnalysisMetricRow[];
}

function metricDataset(dashboard: unknown) {
  const root = asRecord(dashboard);
  const analysis = asRecord(root.analysis);
  const latest = asRecord(root.latest_pipeline);
  const summary = asRecord(latest.summary);
  const reports = asRecord(summary.reports);
  return String(analysis.metrics_dataset || reports.metrics_dataset || '');
}

function chartRows(rows: AnalysisMetricRow[]): ModelMetricDatum[] {
  return rows
    .map((row) => ({
      name: modelName(row),
      r: num(row.R) ?? 0,
      rmse: num(row.RMSE) ?? 0,
      nse: num(row.NSE)
    }))
    .filter((row) => row.r || row.rmse || row.nse !== null);
}

function bestByRmse(rows: ModelMetricDatum[]) {
  const valid = rows.filter((row) => Number.isFinite(row.rmse) && row.rmse > 0);
  if (valid.length) return valid.reduce((best, row) => row.rmse < best.rmse ? row : best);
  return rows.filter((row) => Number.isFinite(row.r)).reduce((best, row) => row.r > best.r ? row : best, rows[0]);
}

function downloads(dashboard: unknown): AnalysisDownload[] {
  const root = asRecord(dashboard);
  const artifacts = asArray(root.artifacts);
  return artifacts
    .map((item) => {
      const url = String(item.download_url || '');
      if (!url) return null;
      const name = String(item.name || item.path || '成果文件');
      const lower = name.toLowerCase();
      const kind: AnalysisDownload['kind'] = lower.match(/\.(png|jpg|jpeg|webp|svg)$/) ? 'chart' : lower.match(/\.(md|txt|docx|pdf|csv|xlsx)$/) ? 'report' : 'artifact';
      return { label: name, url, kind };
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

export function buildAnalysisPanelView(dashboard: unknown): AnalysisPanelView {
  const root = asRecord(dashboard);
  const latest = asRecord(root.latest_pipeline);
  const rows = chartRows(metricRows(root));
  const bestModel = rows.length ? bestByRmse(rows) : undefined;
  const cards = bestModel ? [
    { label: 'R', value: fmt(num(bestModel.r)) },
    { label: 'RMSE', value: fmt(num(bestModel.rmse)) },
    { label: 'NSE', value: fmt(num(bestModel.nse)) }
  ] : [];
  const files = downloads(root);
  const steps = pipelineSteps(root);
  const hasResults = Boolean(rows.length || files.length || steps.length || latest.run_id);

  return {
    hasResults,
    title: String(latest.pipeline_name || '分析结果'),
    status: String(latest.status || ''),
    metricsDataset: metricDataset(root),
    bestModel,
    cards,
    chartData: rows,
    downloads: files,
    steps
  };
}
