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

const workflow = await loadTs('src/components/researchWorkflow.ts');

const plan = workflow.createResearchPlan('我要分析成都市 2019 年土壤水分空间分布');
assert.equal(plan.title, '成都市土壤水分空间分析');
assert.equal(plan.steps.length, 6);
assert.equal(plan.steps[0].status, 'running');
assert.equal(plan.steps[1].status, 'pending');
assert.equal(plan.steps[0].action.kind, 'prompt');
assert.match(plan.steps[0].action.prompt, /工作区数据/);

const shandian = workflow.createResearchPlan('闪电河流域土壤水分融合');
assert.equal(shandian.presetId, 'shandian-soil-moisture');
assert.ok(shandian.steps.some((step) => step.action.kind === 'workflow'));

const updated = workflow.markStepDone(plan, plan.steps[0].id);
assert.equal(updated.steps[0].status, 'done');
assert.equal(updated.steps[1].status, 'running');

const layers = workflow.applyWorkflowAction({ kind: 'layer', layer: 'soil', visible: true });
assert.deepEqual(layers, { kind: 'layer', layer: 'soil', visible: true });

console.log('research workflow tests passed');
