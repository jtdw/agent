import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile('src/components/localLibraryFilters.ts', 'utf8');
const strippedSource = source.replace(/^import type .+;\n/m, '');
const result = ts.transpileModule(strippedSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
    isolatedModules: true
  }
});
const filters = await import(`data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`);

const items = [
  { item_id: '1', name: 'LICENSE_from_source', path: 'data/administrative/china/LICENSE_from_source.txt', data_type: 'document' },
  { item_id: '2', name: 'README_from_source', path: 'data/administrative/china/README_from_source.md', data_type: 'document' },
  { item_id: '3', name: 'china_admin_county_2023', path: 'data/administrative/china_admin_county_2023.zip', data_type: 'archive' },
  { item_id: '4', name: 'field_notes', path: 'data/docs/field_notes.md', data_type: 'document' }
];

assert.deepEqual(filters.filterUserVisibleLibraryItems(items).map((item) => item.item_id), ['3', '4']);
assert.equal(filters.isUserVisibleLibraryItem({ name: 'README.md', path: 'README.md', data_type: 'document' }), false);
assert.equal(filters.isUserVisibleLibraryItem({ name: 'README.md', path: 'README.md', data_type: 'archive' }), true);

console.log('local library filter tests passed');
