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
const appSource = await readFile('src/App.tsx', 'utf8');

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
assert.match(mapStageSource, /allowFallbackStations\?: boolean/, 'MapStage must expose a fallback station toggle');
assert.doesNotMatch(mapStageSource, /if \(!allowFallbackStations\) return;/, 'Disabled fallback must clear stale station state instead of returning early');
assert.match(mapStageSource, /\}, \[userId,\s*allowFallbackStations\]\);/, 'Station loading effect must rerun when fallback policy changes');
assert.equal(mapStageSource.includes('right: 430'), false);
assert.equal(layerPanelSource.includes('type="range"'), false);
assert.equal(layerPanelSource.includes('onLayerOpacityChange'), false);
assert.equal(layerPanelSource.includes('layerOpacity'), false);
assert.equal(mapStageSource.includes('LayerOpacity'), false);
assert.equal(mapStageSource.includes('layerOpacity'), false);
assert.equal(mapStageSource.includes('setLayerPaintIfPresent'), false);
assert.equal(mapStageSource.includes('visibility[kind]'), false);
assert.match(mapStageSource, /isReferenceMapLayer\(layer\)/);
assert.match(mapStageSource, /function rasterPreviewUrl/);
assert.equal(mapStageSource.includes('raster-hue-rotate'), false);
assert.match(appSource, /resultLayerPalettePreferences/);
assert.match(appSource, /mergeResultLayerState\(layers, current, resultLayerPalettePreferences\)/);
assert.match(layerPanelSource, /GlowSwitch/);
assert.equal(layerPanelSource.includes('图层透明度'), false);
assert.equal(layerPanelSource.includes('图例'), false);
assert.match(geometry.measurementLabel([[0, 0], [0, 1]], 'line'), /^长度/);
assert.match(geometry.measurementLabel([[0, 0], [0, 1], [1, 1]], 'polygon'), /^面积/);

assert.deepEqual(commands.parseMapTextCommand('隐藏 DEM'), { kind: 'layer', layer: 'dem', visible: false, reply: '已隐藏 DEM 图层。' });
assert.deepEqual(commands.parseMapTextCommand('给 DEM 换一种配色'), { kind: 'style', target: 'dem', reply: '已为 DEM 图层随机切换配色。' });
assert.deepEqual(commands.parseMapTextCommand('高程换一种配色'), { kind: 'style', target: 'dem', reply: '已为 DEM 图层随机切换配色。' });
assert.deepEqual(commands.parseMapTextCommand('DEM 改成蓝色配色'), { kind: 'style', target: 'dem', palette: 'cyan', reply: '已将 DEM 图层配色切换为 Cyan。' });
assert.deepEqual(commands.parseMapTextCommand('DEM 改成地形配色'), { kind: 'style', target: 'dem', palette: 'terrain', reply: '已将 DEM 图层配色切换为 Terrain。' });
assert.deepEqual(commands.parseMapTextCommand('把所有结果改成黄橙红配色'), { kind: 'style', target: 'all', palette: 'yellow-orange-red', reply: '已将 结果 图层配色切换为 Yellow-Orange-Red。' });
assert.deepEqual(commands.parseMapTextCommand('放大地图'), { kind: 'map', command: 'zoomIn', reply: '已放大地图。' });
assert.deepEqual(commands.parseMapTextCommand('清空绘制'), { kind: 'draw', action: 'clear', reply: '已清空绘制内容。' });
assert.equal(
  commands.parseMapTextCommand('使用当前上传的数据demo_xgboost_soil_moisture.csv训练 XGBoost 土壤水分模型。目标列是 soil_moisture。开启空间分块验证。'),
  null
);

console.log('map upgrade tests passed');
