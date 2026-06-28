import { expect, test } from '@playwright/test';

test('task-card harness renders prediction map presentation result groups', async ({ page }) => {
  await page.goto('/task-card-harness.html');
  await page.waitForLoadState('networkidle');

  await expect(page.getByTestId('task-status-card')).toBeVisible();
  await expect(page.getByTestId('result-groups')).toBeVisible();

  const mapsGroup = page.getByTestId('result-group-maps');
  const imagesGroup = page.getByTestId('result-group-images');
  const modelsGroup = page.getByTestId('result-group-models');
  const mapLayers = page.getByTestId('result-group-map-layers');

  await expect(mapsGroup).toContainText('预测地图');
  await expect(mapsGroup).toContainText('xgboost_raster_prediction.tif');
  await expect(mapsGroup).not.toContainText('summary.json');

  await expect(imagesGroup).toContainText('xgboost_raster_prediction.png');
  await expect(modelsGroup).toContainText('xgboost_raster_prediction_summary.json');
  await expect(mapLayers).toContainText('xgboost_raster_prediction');

  await expect(page.getByText('representative_date=2019-07-15')).toBeVisible();
  await expect(page.getByText(/valid_prediction_pixels=49/)).toBeVisible();
});
