import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile('src/lib/api.ts', 'utf8');
const testSource = source
  .replace(/^import type .+;\n/gm, '')
  .replace(/import\.meta\.env\.VITE_API_BASE/g, "''");
const result = ts.transpileModule(testSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
    isolatedModules: true
  }
});
const apiModule = await import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);

assert.equal(
  apiModule.filenameFromContentDisposition(
    'attachment; filename="fallback.csv"; filename*=UTF-8\'\'%E8%B5%84%E9%98%B3%E5%B8%8290%E7%B1%B3DEM%E7%BB%93%E6%9E%9C.csv',
    'download.csv'
  ),
  '资阳市90米DEM结果.csv'
);

assert.equal(
  apiModule.filenameFromContentDisposition('attachment; filename="plain.csv"', 'download.csv'),
  'plain.csv'
);

assert.equal(
  apiModule.filenameFromContentDisposition('', '默认下载.csv'),
  '默认下载.csv'
);

console.log('api filename tests passed');
