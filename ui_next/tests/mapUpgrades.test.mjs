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
const artifactCardSource = await readFile('src/components/ArtifactDownloadCard.tsx', 'utf8');
const apiSource = await readFile('src/lib/api.ts', 'utf8');

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
assert.match(mapStageSource, /function mapLayerSignature/, 'MapStage must compute stable layer signatures before updating polled layers');
assert.match(mapStageSource, /onResultLayersChange/, 'MapStage must publish result map layers to the surrounding UI');
assert.match(mapStageSource, /fitToResultLayer/, 'MapStage must support fitting to one artifact-level result layer');
assert.match(
  mapStageSource,
  /resultLayerSignatureRef\.current[\s\S]*?setResultLayers\(layers\);/,
  'MapStage must compare the polled layer signature before replacing result layers'
);
assert.equal(mapStageSource.includes('right: 430'), false);
assert.match(layerPanelSource, /resultLayers/, 'LayerPanel must render artifact-level result layers');
assert.match(layerPanelSource, /LayerMetadata/, 'LayerPanel must expose result layer metadata');
assert.match(artifactCardSource, /onShowOnMap/, 'Artifact cards must expose a show-on-map action for map-ready artifacts');
assert.match(apiSource, /refreshMapLayer/, 'Frontend API must expose map layer refresh');
assert.equal(layerPanelSource.includes('图层透明度'), false);
assert.equal(layerPanelSource.includes('图例'), false);
assert.match(geometry.measurementLabel([[0, 0], [0, 1]], 'line'), /^长度/);
assert.match(geometry.measurementLabel([[0, 0], [0, 1], [1, 1]], 'polygon'), /^面积/);

assert.deepEqual(commands.parseMapTextCommand('隐藏 DEM'), { kind: 'layer', layer: 'dem', visible: false, reply: '已隐藏 DEM 图层。' });
assert.deepEqual(commands.parseMapTextCommand('请显示 DEM 图层'), { kind: 'layer', layer: 'dem', visible: true, reply: '已显示 DEM 图层。' });
assert.deepEqual(commands.parseMapTextCommand('放大地图'), { kind: 'map', command: 'zoomIn', reply: '已放大地图。' });
assert.deepEqual(commands.parseMapTextCommand('清空绘制'), { kind: 'draw', action: 'clear', reply: '已清空绘制内容。' });
assert.equal(commands.parseMapTextCommand(`使用当前上传的数据训练 XGBoost 土壤水分模型。
目标列是 soil_moisture。
特征列使用 elevation,slope,precip_7d,ndvi,lst,lon,lat。
时间列是 date。
输出名称为 xgb_sm_demo。
开启空间分块验证，生成预测结果、残差、特征重要性、精度指标和模型文件。`), null);
assert.equal(commands.parseMapTextCommand('请缩小模型预测误差并重新训练'), null);
assert.equal(commands.parseMapTextCommand('定位数据处理失败原因'), null);
assert.equal(commands.parseMapTextCommand('打开土壤水分模型训练结果并分析精度'), null);

console.log('map upgrade tests passed');
