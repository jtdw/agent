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

const model = await loadTs('src/components/chat/chatSessionModel.ts');

const restored = model.deriveNextSessionState({
  result: {
    sessions: [],
    current_session_id: '',
    messages: [
      { role: 'user', content: '什么是 GIS？', session_id: 'session_known' },
      { role: 'assistant', content: 'GIS 是地理信息系统。', session_id: 'session_known' }
    ]
  },
  previousSessionId: ''
});

assert.equal(restored.currentSessionId, 'session_known');
assert.equal(restored.sessions.length, 1);
assert.equal(restored.sessions[0].session_id, 'session_known');
assert.equal(restored.sessions[0].title, '什么是 GIS？');
assert.equal(restored.sessions[0].message_count, 2);

const currentOnly = model.deriveNextSessionState({
  result: {
    sessions: [],
    current_session_id: 'session_current',
    messages: []
  },
  previousSessionId: ''
});

assert.equal(currentOnly.currentSessionId, 'session_current');
assert.equal(currentOnly.sessions.length, 1);
assert.equal(currentOnly.sessions[0].title, '新对话');

const empty = model.deriveNextSessionState({
  result: {
    sessions: [],
    current_session_id: '',
    messages: []
  },
  previousSessionId: ''
});

assert.equal(empty.currentSessionId, '');
assert.deepEqual(empty.sessions, []);

const sidebarFallback = model.sidebarDisplaySessions({
  visibleSessions: [],
  currentSessionId: 'session_visible',
  messagesLength: 4
});

assert.equal(sidebarFallback.length, 1);
assert.equal(sidebarFallback[0].session_id, 'session_visible');
assert.equal(sidebarFallback[0].message_count, 4);

const sidebarLocalFallback = model.sidebarDisplaySessions({
  visibleSessions: [],
  currentSessionId: '',
  messagesLength: 4
});

assert.equal(sidebarLocalFallback.length, 1);
assert.equal(sidebarLocalFallback[0].session_id, '');
assert.equal(sidebarLocalFallback[0].title, '当前对话');
assert.equal(sidebarLocalFallback[0].message_count, 4);

console.log('chatSessionModel.test.mjs passed');
