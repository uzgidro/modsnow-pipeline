"""
Обработка MODIS MOD10A1F: мозаика тайлов → расчёт SCA по бассейнам.

Пайплайн:
  1. Чтение HDF тайлов (CGF_NDSI_Snow_Cover)
  2. Мозаика тайлов в единый растр
  3. Клиппинг по полигонам бассейнов (shapefile)
  4. Бинарная классификация снега (NDSI >= 40)
  5. Расчёт % снежного покрова (SCA) для каждого бассейна
  6. Расчёт SCA по высотным зонам (500м)
"""

import glob
import logging
from pathlib import Path

import geopandas as gpd
import netCDF4
import numpy as np
import shapely
from pyproj import Transformer
from shapely import segmentize
from shapely.ops import transform as shapely_transform

logger = logging.getLogger(__name__)

# === Константы MODIS Sinusoidal ===
TILE_SIZE = 2400
CELL_SIZE = 463.31271653  # метров (500м номинально)
R = 6371007.181  # радиус Земли в метрах
UPPER_LEFT_X = -20015109.354
UPPER_LEFT_Y = 10007554.677

NDSI_THRESHOLD = 40
ZONE_EXTENT = 500


def read_ascii_grid(filepath: str) -> tuple:
    """Прочитать ESRI ASCII Grid файл (.asc). Используется для DEM и масок воды."""
    with open(filepath, "r") as f:
        ncols = int(f.readline().split()[1])
        nrows = int(f.readline().split()[1])
        xll = float(f.readline().split()[1])
        yll = float(f.readline().split()[1])
        cellsize = float(f.readline().split()[1])
        nodata = float(f.readline().split()[1])
        data = np.loadtxt(f).reshape(nrows, ncols)
    return data, xll, yll, cellsize, nodata, ncols, nrows


def grid_lookup_vectorized(
    lons: np.ndarray, lats: np.ndarray,
    data: np.ndarray, xll: float, yll: float,
    cellsize: float, ncols: int, nrows: int, nodata: float,
) -> np.ndarray:
    """Векторизованный поиск значений грида по координатам WGS84."""
    cols = ((lons - xll) / cellsize).astype(int)
    rows = ((yll + nrows * cellsize - lats) / cellsize).astype(int)
    valid = (rows >= 0) & (rows < nrows) & (cols >= 0) & (cols < ncols)
    result = np.full(len(lons), nodata, dtype=data.dtype)
    result[valid] = data[rows[valid], cols[valid]]
    return result


def derive_code(name: str) -> str:
    """Код бассейна из имени (как в R: tolower + gsub(' +', '_'))."""
    return name.lower().replace(" ", "_")


def tile_to_sinusoidal_bounds(h: int, v: int) -> tuple:
    """Координаты тайла (h, v) в метрах Sinusoidal."""
    tile_width = TILE_SIZE * CELL_SIZE
    x_min = UPPER_LEFT_X + h * tile_width
    y_max = UPPER_LEFT_Y - v * tile_width
    x_max = x_min + tile_width
    y_min = y_max - tile_width
    return x_min, y_min, x_max, y_max


def parse_tile_id(filename: str) -> tuple:
    """Извлечь h, v из имени файла MOD10A1F.A2025335.h23v04.061...hdf"""
    parts = Path(filename).stem.split(".")
    tile_str = parts[2]  # h23v04
    h = int(tile_str[1:3])
    v = int(tile_str[4:6])
    return h, v


def read_snow_tile(filepath: str) -> np.ndarray:
    """Прочитать CGF_NDSI_Snow_Cover из HDF файла."""
    with netCDF4.Dataset(filepath) as ds:
        return ds.variables["CGF_NDSI_Snow_Cover"][:]


def mosaic_tiles(hdf_dir: str) -> tuple:
    """
    Мозаика всех HDF тайлов в один массив.
    Возвращает (mosaic_array, x_min, y_min, x_max, y_max) в Sinusoidal.
    """
    hdf_files = sorted(glob.glob(str(Path(hdf_dir) / "*.hdf")))
    if not hdf_files:
        raise FileNotFoundError(f"Нет HDF файлов в {hdf_dir}")

    tiles = {}
    for f in hdf_files:
        h, v = parse_tile_id(f)
        tiles[(h, v)] = f

    h_vals = sorted(set(h for h, v in tiles))
    v_vals = sorted(set(v for h, v in tiles))
    h_min, h_max = min(h_vals), max(h_vals)
    v_min, v_max = min(v_vals), max(v_vals)

    n_h = h_max - h_min + 1
    n_v = v_max - v_min + 1

    logger.info("Тайлы: h=%d-%d, v=%d-%d (%dx%d)", h_min, h_max, v_min, v_max, n_h, n_v)

    mosaic = np.full((n_v * TILE_SIZE, n_h * TILE_SIZE), 255, dtype=np.uint8)

    for (h, v), filepath in tiles.items():
        data = read_snow_tile(filepath)
        row = (v - v_min) * TILE_SIZE
        col = (h - h_min) * TILE_SIZE
        mosaic[row : row + TILE_SIZE, col : col + TILE_SIZE] = data

    tile_width = TILE_SIZE * CELL_SIZE
    x_min = UPPER_LEFT_X + h_min * tile_width
    y_max = UPPER_LEFT_Y - v_min * tile_width
    x_max = UPPER_LEFT_X + (h_max + 1) * tile_width
    y_min = UPPER_LEFT_Y - (v_max + 1) * tile_width

    logger.info("Мозаика: %s (%.0f x %.0f км)",
                mosaic.shape, mosaic.shape[1]*CELL_SIZE/1000, mosaic.shape[0]*CELL_SIZE/1000)
    return mosaic, x_min, y_min, x_max, y_max


def calc_sca_for_catchment(
    mosaic: np.ndarray,
    mosaic_bounds: tuple,
    geometry,
    transformer: Transformer,
    inverse_transformer: Transformer = None,
    water_mask_info: tuple = None,
    dem_info: tuple = None,
) -> dict:
    """
    Рассчитать SCA (Snow Cover Area %) для одного бассейна.
    Бинарная классификация: NDSI >= 40 = снег (стандарт MODIS).
    """
    x_min, y_min, x_max, y_max = mosaic_bounds
    rows, cols = mosaic.shape

    geom_dense = segmentize(geometry, max_segment_length=0.01)
    geom_sinu = shapely_transform(transformer.transform, geom_dense)

    sx_min, sy_min, sx_max, sy_max = geom_sinu.bounds
    col_start = max(0, int((sx_min - x_min) / CELL_SIZE))
    col_end = min(cols, int((sx_max - x_min) / CELL_SIZE) + 1)
    row_start = max(0, int((y_max - sy_max) / CELL_SIZE))
    row_end = min(rows, int((y_max - sy_min) / CELL_SIZE) + 1)

    empty = {"sca_pct": None, "zones": []}
    if col_start >= col_end or row_start >= row_end:
        return empty

    subset = mosaic[row_start:row_end, col_start:col_end]
    n_rows_sub = row_end - row_start
    n_cols_sub = col_end - col_start

    pixel_xs = x_min + (col_start + np.arange(n_cols_sub) + 0.5) * CELL_SIZE
    pixel_ys = y_max - (row_start + np.arange(n_rows_sub) + 0.5) * CELL_SIZE

    xs_grid, ys_grid = np.meshgrid(pixel_xs, pixel_ys)
    points = shapely.points(xs_grid.ravel(), ys_grid.ravel())
    poly_mask = shapely.contains(geom_sinu, points).reshape(n_rows_sub, n_cols_sub)

    in_rows, in_cols = np.where(poly_mask)
    if len(in_rows) == 0:
        return empty

    sinu_xs = pixel_xs[in_cols]
    sinu_ys = pixel_ys[in_rows]

    is_water = np.zeros(len(in_rows), dtype=bool)
    elevations = np.full(len(in_rows), np.nan)

    if inverse_transformer is not None and (water_mask_info or dem_info):
        wgs_lons, wgs_lats = inverse_transformer.transform(sinu_xs, sinu_ys)

        if water_mask_info is not None:
            wm_data, wm_xll, wm_yll, wm_cs, wm_nd, wm_nc, wm_nr = water_mask_info
            wm_vals = grid_lookup_vectorized(
                wgs_lons, wgs_lats, wm_data, wm_xll, wm_yll, wm_cs, wm_nc, wm_nr, wm_nd)
            is_water = (wm_vals > 0) & (wm_vals != wm_nd)

        if dem_info is not None:
            dem_data, dem_xll, dem_yll, dem_cs, dem_nd, dem_nc, dem_nr = dem_info
            elev_vals = grid_lookup_vectorized(
                wgs_lons, wgs_lats, dem_data, dem_xll, dem_yll, dem_cs, dem_nc, dem_nr, dem_nd)
            elevations = np.where(elev_vals != dem_nd, elev_vals, np.nan)

    ndsi_values = subset[in_rows, in_cols].astype(np.float64)
    valid_ndsi = (ndsi_values >= 0) & (ndsi_values <= 100)
    not_water = ~is_water
    valid = valid_ndsi & not_water

    snow = (ndsi_values >= NDSI_THRESHOLD) & valid

    valid_count = int(np.sum(valid))
    snow_count = int(np.sum(snow))
    sca_pct = round(snow_count / valid_count * 100, 2) if valid_count > 0 else None

    zones = []
    if dem_info is not None:
        valid_elev = elevations[valid]
        valid_snow = snow[valid]
        has_elev = ~np.isnan(valid_elev)

        if has_elev.any():
            zone_labels = np.ceil(valid_elev[has_elev] / ZONE_EXTENT) * ZONE_EXTENT
            snow_with_elev = valid_snow[has_elev]

            for z in sorted(np.unique(zone_labels)):
                z_mask = zone_labels == z
                z_valid = int(np.sum(z_mask))
                z_snow = int(np.sum(snow_with_elev[z_mask]))
                z_sca = round(z_snow / z_valid * 100, 2) if z_valid > 0 else None
                zones.append({
                    "min_elev": int(z - ZONE_EXTENT),
                    "max_elev": int(z),
                    "sca_pct": z_sca,
                })

    return {
        "sca_pct": sca_pct,
        "zones": zones,
    }


def process_day(hdf_dir: str, data_dir: str = "data") -> list:
    """
    Обработка одного дня: мозаика → SCA для всех бассейнов.
    """
    base = Path(data_dir)
    shapefile_path = base / "ca_catchments.shp"

    logger.info("Обработка: %s", hdf_dir)

    # 1. Мозаика
    logger.info("Мозаика тайлов...")
    mosaic, x_min, y_min, x_max, y_max = mosaic_tiles(hdf_dir)
    mosaic_bounds = (x_min, y_min, x_max, y_max)

    # 2. Загрузить бассейны из шейпфайла
    logger.info("Загрузка бассейнов...")
    gdf = gpd.read_file(str(shapefile_path))
    if "PROCESS" in gdf.columns:
        gdf = gdf[gdf["PROCESS"] == 1]
    logger.info("Бассейнов (PROCESS=1): %d", len(gdf))

    # 3. Трансформеры
    sinu_crs = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext"
    transformer = Transformer.from_crs("EPSG:4326", sinu_crs, always_xy=True)
    inverse_transformer = Transformer.from_crs(sinu_crs, "EPSG:4326", always_xy=True)

    # 4. Расчёт SCA
    logger.info("Расчёт SCA по бассейнам (NDSI >= %d, зоны %dм)...", NDSI_THRESHOLD, ZONE_EXTENT)
    results = []
    for _, row in gdf.iterrows():
        name = row.get("Name", "?")
        geom = row.geometry
        if geom is None:
            continue

        code = derive_code(name)

        water_mask_info = None
        wm_path = base / f"{code}_water_mask.asc"
        if wm_path.exists():
            try:
                water_mask_info = read_ascii_grid(str(wm_path))
            except (ValueError, IndexError):
                pass

        dem_info = None
        dem_path = base / f"{code}_dem500m.asc"
        if dem_path.exists():
            dem_info = read_ascii_grid(str(dem_path))

        sca = calc_sca_for_catchment(
            mosaic, mosaic_bounds, geom, transformer,
            inverse_transformer, water_mask_info, dem_info,
        )
        sca["name"] = name
        results.append(sca)

        if sca["sca_pct"] is not None:
            zones_str = f" ({len(sca['zones'])} зон)" if sca.get("zones") else ""
            logger.info("  %-30s SCA: %6.1f%%%s", name, sca["sca_pct"], zones_str)
        else:
            logger.info("  %-30s нет данных", name)

    return results
