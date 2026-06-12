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

const geometry = await loadTs('src/components/mapGeometry.ts');
const commands = await loadTs('src/components/mapTextCommands.ts');
const mapStageSource = await readFile('src/components/MapStage.tsx', 'utf8');
const layerPanelSource = await readFile('src/components/LayerPanel.tsx', 'utf8');

assert.equal(Math.round(geometry.distanceMeters([0, 0], [0, 1])), 111195);
assert.equal(geometry.drawGeoJson([[0, 0], [0, 1], [1, 1]], 'polygon').features.length, 5);
assert.equal(mapStageSource.includes('demo_aoi'), false);
assert.equal(mapStageSource.includes('raiseStationLayers'), true);
assert.equal(mapStageSource.includes('setStationMarkers'), true);
assert.equal(mapStageSource.includes("id: 'station_points_core'"), false);
assert.equal(mapStageSource.includes('SvgDataFallback'), false);
assert.match(mapStageSource, /function normalizeMapBounds/);
assert.match(mapStageSource, /function safeFitBounds/);
assert.match(mapStageSource, /clientWidth|offsetWidth/);
assert.match(mapStageSource, /Number\.isFinite/);
assert.equal(mapStageSource.includes('right: 430'), false);
assert.equal(layerPanelSource.includes('图层透明度'), false);
assert.equal(layerPanelSource.includes('图例'), false);
assert.match(geometry.measurementLabel([[0, 0], [0, 1]], 'line'), /^长度/);
assert.match(geometry.measurementLabel([[0, 0], [0, 1], [1, 1]], 'polygon'), /^面积/);

assert.deepEqual(commands.parseMapTextCommand('隐藏 DEM'), { kind: 'layer', layer: 'dem', visible: false, reply: '已隐藏 DEM 图层。' });
assert.deepEqual(commands.parseMapTextCommand('放大地图'), { kind: 'map', command: 'zoomIn', reply: '已放大地图。' });
assert.deepEqual(commands.parseMapTextCommand('清空绘制'), { kind: 'draw', action: 'clear', reply: '已清空绘制内容。' });

console.log('map upgrade tests passed');
