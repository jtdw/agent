from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box


def write_raster(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(100.0, 31.0, 0.01, 0.01),
        nodata=-9999.0,
    ) as dst:
        dst.write(data.astype("float32"), 1)


def main() -> None:
    root = Path(__file__).resolve().parent
    n = 80
    x = np.linspace(0.05, 0.95, n)
    categories = np.where(np.arange(n) % 3 == 0, "valley", np.where(np.arange(n) % 3 == 1, "plain", "ridge"))
    points = pd.DataFrame(
        {
            "id": [f"p{i:03d}" for i in range(n)],
            "lon": 100.0 + x,
            "lat": 31.0 - x,
            "dem_feature": 100 + 50 * x,
            "ndvi_feature": 0.2 + 0.6 * x,
            "rainfall_feature": 30 + 8 * np.sin(x * np.pi),
            "landform": categories,
            "target_regression": 2 + 3 * x + (categories == "ridge") * 0.5,
            "target_classification": np.where(x > 0.55, "high", "low"),
        }
    )
    points.to_csv(root / "points.csv", index=False)

    cells = []
    attrs = []
    for row in range(3):
        for col in range(3):
            geom = box(100 + col * 0.2, 30.4 + row * 0.2, 100.18 + col * 0.2, 30.58 + row * 0.2)
            feature_a = col + row * 0.5
            feature_b = 10 + row + col
            cells.append(geom)
            attrs.append({"id": f"poly_{row}_{col}", "feature_a": feature_a, "feature_b": feature_b, "target": 1.5 * feature_a + 0.2 * feature_b})
    gpd.GeoDataFrame(attrs, geometry=cells, crs="EPSG:4326").to_file(root / "polygons.geojson", driver="GeoJSON")

    yy, xx = np.mgrid[0:100, 0:100].astype("float32")
    dem = 100 + xx + yy * 0.2
    ndvi = 0.15 + xx / 150
    lst = 290 + yy / 5
    rainfall = 20 + np.sin(xx / 10) * 3 + yy / 20
    write_raster(root / "raster_features" / "dem.tif", dem)
    write_raster(root / "raster_features" / "ndvi.tif", ndvi)
    write_raster(root / "raster_features" / "lst.tif", lst)
    write_raster(root / "raster_features" / "rainfall.tif", rainfall)
    write_raster(root / "target.tif", 0.05 * dem + 2.0 * ndvi - 0.01 * lst + 0.1 * rainfall)


if __name__ == "__main__":
    main()
