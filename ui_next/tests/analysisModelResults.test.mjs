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

const { buildAnalysisPanelView } = await loadTs('src/components/analysisPanelData.ts');

const dashboard = {
  model_results: [
    {
      model_result_id: 'model_result_xgb_001',
      model: 'XGBoost',
      metrics_dataset: 'soil_demo_xgb_metrics',
      metrics: { R: 0.91, RMSE: 0.12, NSE: 0.8 },
      artifacts: [
        { artifact_id: 'artifact_soil_demo_xgb_metrics', label: '指标表', path: 'workspace/derived/soil_demo_xgb_metrics.csv', download_url: '/api/files/artifact?path=derived/soil_demo_xgb_metrics.csv' }
      ],
      recommendations: ['RMSE 较低，可继续做 GCP 不确定性分析。']
    }
  ],
  artifacts: []
};

const view = buildAnalysisPanelView(dashboard);
assert.equal(view.hasResults, true);
assert.equal(view.metricsDataset, 'soil_demo_xgb_metrics');
assert.equal(view.bestModel?.name, 'XGBoost');
assert.equal(view.bestModel?.modelResultId, 'model_result_xgb_001');
assert.equal(view.downloads[0]?.label, '指标表');
assert.equal(view.downloads[0]?.artifactId, 'artifact_soil_demo_xgb_metrics');
assert.equal(view.downloads[0]?.url, '');
assert.match(view.recommendations.join('\n'), /GCP/);

console.log('analysisModelResults.test.mjs passed');
