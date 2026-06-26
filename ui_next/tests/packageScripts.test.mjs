import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const pkg = JSON.parse(await readFile('package.json', 'utf8'));

assert.equal(pkg.scripts?.lint, 'tsc -b --pretty false', 'ui_next should expose a dependency-free lint script backed by TypeScript checks');

console.log('packageScripts.test.mjs passed');
