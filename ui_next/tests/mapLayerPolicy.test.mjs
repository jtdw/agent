import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile('src/components/mapLayerPolicy.ts', 'utf8');
const result = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
    isolatedModules: true
  }
});

const moduleUrl = `data:text/javascript;base64,${Buffer.from(result.outputText).toString('base64')}`;
const policy = await import(moduleUrl);

assert.deepEqual(policy.getDrawLayerVisibility({ dem: true, boundary: true, stations: true, soil: false }), {
  visible: true,
  layers: ['draw_polygon', 'draw_line', 'draw_points']
});

assert.deepEqual(policy.getOverlayVisibilityPlan({ dem: false, boundary: true, stations: false, soil: true }), {
  stations: { visible: false, layers: ['station_points_halo', 'station_points_core'] },
  boundary: { visible: true, layers: ['demo_aoi_fill', 'demo_aoi_line'] },
  draw: { visible: true, layers: ['draw_polygon', 'draw_line', 'draw_points'] }
});

assert.equal(policy.isLocalSecureContext('http:', '127.0.0.1'), true);
assert.equal(policy.isLocalSecureContext('http:', 'localhost'), true);
assert.equal(policy.isLocalSecureContext('https:', '192.168.1.8'), true);
assert.equal(policy.isLocalSecureContext('http:', '192.168.1.8'), false);

console.log('map layer policy tests passed');
