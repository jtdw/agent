import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function loadTs(path) {
  const source = await readFile(path, 'utf8');
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      isolatedModules: true
    }
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);
}

const analysis = await loadTs('src/components/analysisPanelData.ts');

const dashboard = {
  latest_pipeline: {
    run_id: 'run_1',
    pipeline_name: 'database_training_pipeline',
    status: 'success',
    summary: {
      reports: {
        metrics_dataset: 'soil_combined_metrics',
        comparison_summary: '模型比较摘要已生成'
      }
    },
    steps: [
      { step_name: '汇总模型指标', status: 'success', output_summary: '生成统一指标表 soil_combined_metrics' }
    ]
  },
  analysis: {
    metrics_dataset: 'soil_combined_metrics',
    metric_rows: [
      { model: 'BTCH', predicted: 'btch', R: 0.62, RMSE: 0.046, NSE: 0.38 },
      { model: 'RF', predicted: 'rf', R: 0.7, RMSE: 0.039, NSE: 0.47 },
      { model: 'XGBoost', predicted: 'xgb', R: 0.73, RMSE: 0.036, NSE: 0.51 },
      { model: 'LSTM', predicted: 'lstm', R: 0.69, RMSE: 0.041, NSE: 0.44 }
    ]
  },
  artifacts: [
    { artifact_id: 'artifact_summary_001', name: 'soil_model_summary.md', path: 'derived/soil_model_summary.md', download_url: '/api/files/artifact?path=derived/soil_model_summary.md', type: 'document' },
    { artifact_id: 'artifact_plot_001', name: 'soil_metrics_fig_metric_r.png', path: 'plots/soil_metrics_fig_metric_r.png', download_url: '/api/files/artifact?path=plots/soil_metrics_fig_metric_r.png', type: 'plot' }
  ]
};

const view = analysis.buildAnalysisPanelView(dashboard);
assert.equal(view.hasResults, true);
assert.equal(view.title, 'database_training_pipeline');
assert.deepEqual(view.cards.map((card) => [card.label, card.value]), [['R', '0.730'], ['RMSE', '0.036'], ['NSE', '0.510']]);
assert.deepEqual(view.chartData.map((row) => row.name), ['BTCH', 'RF', 'XGBoost', 'LSTM']);
assert.equal(view.bestModel?.name, 'XGBoost');
assert.equal(view.bestModel?.modelResultId, '');
assert.equal(view.downloads.length, 2);
assert.equal(view.downloads[0].artifactId, 'artifact_summary_001');
assert.equal(view.downloads[1].artifactId, 'artifact_plot_001');

const boundModelView = analysis.buildAnalysisPanelView({
  model_results: [
    { model_result_id: 'model_result_xgb_001', model: 'XGBoost', metrics_dataset: 'xgb_metrics', metrics: { R: 0.8, RMSE: 0.1, NSE: 0.7 } }
  ],
  artifacts: []
});
assert.equal(boundModelView.bestModel?.modelResultId, 'model_result_xgb_001');

const empty = analysis.buildAnalysisPanelView({ artifacts: [], latest_pipeline: null, analysis: {} });
assert.equal(empty.hasResults, false);
assert.equal(empty.cards.length, 0);
assert.equal(empty.downloads.length, 0);

const resultPanelView = analysis.buildAnalysisPanelView(
  { artifacts: [], latest_pipeline: null, analysis: {} },
  {
    has_results: true,
    title: 'XGBoost model finished',
    files: [
      { artifact_id: 'artifact_metrics_001', label: 'metrics', path: 'derived/xgb_metrics.csv', download_url: '/api/files/artifact?path=derived/xgb_metrics.csv', kind: 'report' }
    ],
    recommendations: ['check metrics']
  }
);
assert.equal(resultPanelView.hasResults, true);
assert.equal(resultPanelView.title, 'XGBoost model finished');
assert.equal(resultPanelView.downloads.length, 1);
assert.equal(resultPanelView.downloads[0].label, 'metrics');
assert.equal(resultPanelView.downloads[0].artifactId, 'artifact_metrics_001');
assert.equal(resultPanelView.recommendations[0], 'check metrics');

console.log('analysis panel data tests passed');
