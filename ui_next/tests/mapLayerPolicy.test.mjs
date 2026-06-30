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
  stations: { visible: false, layers: [] },
  boundary: { visible: true, layers: [] },
  draw: { visible: true, layers: ['draw_polygon', 'draw_line', 'draw_points'] }
});

assert.equal(policy.isLocalSecureContext('http:', '127.0.0.1'), true);
assert.equal(policy.isLocalSecureContext('http:', 'localhost'), true);
assert.equal(policy.isLocalSecureContext('https:', '192.168.1.8'), true);
assert.equal(policy.isLocalSecureContext('http:', '192.168.1.8'), false);

const demoLayers = [
  { id: 'dem_a', name: 'DEM A', kind: 'dem', type: 'raster' },
  { id: 'soil_a', name: 'Soil A', kind: 'soil', type: 'vector' }
];
const mergedState = policy.mergeResultLayerState(demoLayers, {
  dem_a: { visible: false, removed: false, palette: 'terrain' },
  stale: { visible: false, removed: true, palette: 'viridis' }
});
assert.equal(mergedState.dem_a.visible, false);
assert.equal(mergedState.dem_a.palette, 'terrain');
assert.equal(mergedState.soil_a.visible, true);
assert.equal(mergedState.soil_a.palette, 'moisture');
assert.equal(mergedState.stale.removed, true);
assert.deepEqual(policy.visibleResultLayers(demoLayers, { dem_a: { visible: false, removed: false, palette: 'terrain' } }), [demoLayers[1]]);
assert.deepEqual(policy.resultLayerPalette('terrain').colors, ['#2d5a27', '#8fbf5a', '#f6e27f', '#c77c3a', '#f8fafc']);
assert.equal(policy.nextPaletteName('terrain', 0), 'magma');
assert.equal(policy.mergeResultLayerState([{ id: 'dem_b', kind: 'dem' }], {}, { dem: 'magma' }).dem_b.palette, 'magma');
assert.equal(policy.mergeResultLayerState([{ id: 'soil_b', kind: 'soil' }], {}, { all: 'rainbow' }).soil_b.palette, 'rainbow');
assert.equal(policy.mergeResultLayerState([{ id: 'dem_c', kind: 'dem' }], { dem_c: { visible: true, removed: false, palette: 'cyan' } }, { dem: 'magma' }).dem_c.palette, 'cyan');
assert.equal(policy.isReferenceMapLayer({ id: 'local_library_shandianhe_basin_boundary', kind: 'boundary', meta: { source: 'local_library' } }), true);
assert.equal(policy.isReferenceMapLayer({ id: 'dataset_shandianhe_basin_boundary', name: '闪电河流域边界', kind: 'boundary', meta: { source: 'local_library', item_id: 'lib_shandianhe_basin_boundary_full' } }), true);
assert.equal(policy.isReferenceMapLayer({ id: 'dataset_user_dem', kind: 'dem', meta: { source: 'upload' } }), false);
assert.doesNotMatch(source, /source_path/, 'Reference map layer policy must not depend on private backend path metadata');

console.log('map layer policy tests passed');
