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

const model = await loadTs('src/components/chat/taskCardModel.ts');

const runningPresentation = model.buildTaskCardPresentation({
  message: {
    role: 'assistant',
    content: '',
    meta: {
      task_card: {
        title: '工作区检查与处理计划',
        current_step: '正在验证矢量边界与栅格范围是否重叠'
      },
      management_view: {
        status: 'running',
        user_message: '正在检查输入数据。',
        action_state: { validate: 'running' }
      },
      execution_summary: {
        summary: '拆解为数据检查、参数校验、工具调用和成果注册。'
      }
    }
  },
  result: {
    status: 'running',
    data_sources: ['uploaded_boundary.geojson'],
    executed_steps: [
      { step_id: 'read-context', tool_name: 'workspace_profile', status: 'succeeded' },
      { step_id: 'validate-input', tool_name: 'vector_validate', status: 'running' }
    ]
  }
});

assert.equal(runningPresentation.status, 'running');
assert.equal(runningPresentation.progress, null, 'missing backend progress must not become a fake percentage');
assert.match(runningPresentation.thinking.summary, /正在检查|已完成/, 'task card should expose a concise public thinking summary');
assert.ok(runningPresentation.thinking.steps.length >= 3, 'task card should expose multiple public process steps');
assert.equal(runningPresentation.thinking.defaultExpanded, true, 'running tool tasks should show process by default');
assert.ok(
  runningPresentation.thinking.steps.some((step) => /读取|工作区|上下文/.test(step.title + step.detail)),
  'public process should include workspace/context reading'
);
assert.ok(
  runningPresentation.thinking.steps.some((step) => /验证|检查|validate/.test(step.title + step.detail)),
  'public process should include data validation'
);

const waitingPresentation = model.buildTaskCardPresentation({
  message: {
    role: 'assistant',
    content: '',
    meta: {
      action_required: {
        type: 'confirmation_required',
        confirmation_prompt: '确认执行',
        confirmed_action_id: 'confirm_1'
      }
    }
  },
  result: null
});

assert.equal(waitingPresentation.status, 'awaiting_confirmation');
assert.match(waitingPresentation.thinking.summary, /确认|执行/, 'confirmation tasks should explain that execution is gated');
assert.equal(waitingPresentation.thinking.defaultExpanded, true);

const sanitized = model.buildTaskCardPresentation({
  message: {
    role: 'assistant',
    content: '',
    meta: {
      status: 'failed',
      task_card: {
        current_step: '读取 C:\\Users\\demo\\.env 并检查 token=secret storage_state.json'
      },
      execution_summary: {
        summary: 'Traceback: cookie token leaked at C:\\secret\\storage_state.json'
      }
    }
  },
  result: {
    status: 'failed',
    error_summary: '失败，详见 C:\\secret\\.env token=abc'
  }
});

const serialized = JSON.stringify(sanitized.thinking);
assert.doesNotMatch(serialized, /C:\\|\.env|token=|cookie|storage_state|Traceback/i, 'public thinking must redact sensitive implementation details');
assert.match(serialized, /已隐藏敏感细节|失败|无法继续/, 'sanitized process should still remain user-readable');

console.log('taskCardModel.test.mjs passed');
