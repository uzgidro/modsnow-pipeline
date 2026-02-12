"""
Обработка ERA5-Land snow depth: средняя глубина снега по бассейнам.

Пайплайн:
  1. Чтение NetCDF (переменная sde — snow depth в метрах)
  2. Загрузка бассейнов из шейпфайла (PROCESS=1)
  3. Для каждого бассейна: средняя глубина по ячейкам внутри полигона
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import netCDF4
import numpy as np
from shapely.geometry import Point
from shapely.prepared import prep

logger = logging.getLogger(__name__)


def process_snow_depth(nc_path: str, data_dir: str = "data") -> dict:
    """
    Рассчитать среднюю глубину снега (м) для каждого активного бассейна.

    Args:
        nc_path: Путь к NetCDF файлу ERA5-Land snow_depth.
        data_dir: Директория с шейпфайлом бассейнов.

    Returns:
        dict[name, float] — глубина снега в метрах для каждого бассейна.
    """
    # 1. Прочитать NetCDF
    ds = netCDF4.Dataset(nc_path)
    try:
        # ERA5-Land: переменная sde (snow depth water equivalent... actually snow_depth)
        # Variable name may be 'sde' or 'sd' depending on CDS version
        for var_name in ("sde", "sd", "snow_depth"):
            if var_name in ds.variables:
                sde = ds.variables[var_name][:].squeeze()
                break
        else:
            available = [k for k in ds.variables if k not in ("latitude", "longitude", "time")]
            raise KeyError(f"snow depth variable not found, available: {available}")

        lat = ds.variables["latitude"][:]
        lon = ds.variables["longitude"][:]
    finally:
        ds.close()

    logger.info("ERA5 grid: %d lat x %d lon, sde shape %s", len(lat), len(lon), sde.shape)

    # Убедимся что lat отсортирована по убыванию (north → south)
    if lat[0] < lat[-1]:
        lat = lat[::-1]
        sde = sde[::-1, :]

    # 2. Загрузить бассейны
    shapefile_path = Path(data_dir) / "ca_catchments.shp"
    gdf = gpd.read_file(str(shapefile_path))
    if "PROCESS" in gdf.columns:
        gdf = gdf[gdf["PROCESS"] == 1]

    # 3. Для каждого бассейна — средняя глубина снега
    result = {}
    for _, row in gdf.iterrows():
        name = row.get("Name", "?")
        geom = row.geometry
        if geom is None:
            continue

        # Bounding box полигона
        minx, miny, maxx, maxy = geom.bounds

        # Индексы ячеек ERA5 внутри bbox (с запасом в 1 ячейку)
        dlat = abs(lat[1] - lat[0]) if len(lat) > 1 else 0.1
        dlon = abs(lon[1] - lon[0]) if len(lon) > 1 else 0.1

        lat_mask = (lat >= miny - dlat) & (lat <= maxy + dlat)
        lon_mask = (lon >= minx - dlon) & (lon <= maxx + dlon)

        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]

        if len(lat_idx) == 0 or len(lon_idx) == 0:
            logger.debug("  %s: нет ячеек ERA5 в bbox", name)
            continue

        # Точечная проверка: центры ячеек внутри полигона
        prepared_geom = prep(geom)
        values = []

        for i in lat_idx:
            for j in lon_idx:
                if prepared_geom.contains(Point(float(lon[j]), float(lat[i]))):
                    val = float(sde[i, j])
                    if not np.isnan(val) and val >= 0:
                        values.append(val)

        if values:
            mean_depth = round(np.mean(values), 4)
            result[name] = mean_depth
            logger.info("  %-30s snow_depth: %.4f m (%d cells)", name, mean_depth, len(values))
        else:
            logger.info("  %-30s нет данных", name)

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if len(sys.argv) < 2:
        print("Usage: python process_era5.py path/to/snow_depth.nc")
        sys.exit(1)
    depths = process_snow_depth(sys.argv[1])
    print("\nResults:")
    for name, depth in sorted(depths.items()):
        print(f"  {name}: {depth:.4f} m")
