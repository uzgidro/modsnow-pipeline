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
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import netCDF4
import numpy as np
from pyproj import Transformer
from shapely import segmentize
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform
from shapely.prepared import prep

# === Константы MODIS Sinusoidal ===
# Размер тайла MODIS: 2400x2400 пикселей, ~10° x 10° на экваторе
TILE_SIZE = 2400
CELL_SIZE = 463.31271653  # метров (500м номинально)
# Параметры проекции MODIS Sinusoidal
R = 6371007.181  # радиус Земли в метрах
UPPER_LEFT_X = -20015109.354
UPPER_LEFT_Y = 10007554.677


NDSI_THRESHOLD = 40  # стандартный порог MODIS для классификации снега
ZONE_EXTENT = 500    # ширина высотной зоны в метрах


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
    ds = netCDF4.Dataset(filepath)
    data = ds.variables["CGF_NDSI_Snow_Cover"][:]
    ds.close()
    return data


def mosaic_tiles(hdf_dir: str) -> tuple:
    """
    Мозаика всех HDF тайлов в один массив.
    Возвращает (mosaic_array, x_min, y_min, x_max, y_max) в Sinusoidal.
    """
    hdf_files = sorted(glob.glob(str(Path(hdf_dir) / "*.hdf")))
    if not hdf_files:
        raise FileNotFoundError(f"Нет HDF файлов в {hdf_dir}")

    # Определить сетку тайлов
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

    print(f"  Тайлы: h={h_min}-{h_max}, v={v_min}-{v_max} ({n_h}x{n_v})")

    # Создать пустой массив (255 = fill)
    mosaic = np.full((n_v * TILE_SIZE, n_h * TILE_SIZE), 255, dtype=np.uint8)

    for (h, v), filepath in tiles.items():
        data = read_snow_tile(filepath)
        row = (v - v_min) * TILE_SIZE
        col = (h - h_min) * TILE_SIZE
        mosaic[row : row + TILE_SIZE, col : col + TILE_SIZE] = data

    # Границы мозаики в Sinusoidal
    tile_width = TILE_SIZE * CELL_SIZE
    x_min = UPPER_LEFT_X + h_min * tile_width
    y_max = UPPER_LEFT_Y - v_min * tile_width
    x_max = UPPER_LEFT_X + (h_max + 1) * tile_width
    y_min = UPPER_LEFT_Y - (v_max + 1) * tile_width

    print(f"  Мозаика: {mosaic.shape} ({mosaic.shape[1]*CELL_SIZE/1000:.0f} x {mosaic.shape[0]*CELL_SIZE/1000:.0f} км)")
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
    Опционально: маска воды и расчёт по высотным зонам.
    """
    x_min, y_min, x_max, y_max = mosaic_bounds
    rows, cols = mosaic.shape

    # Уплотнить полигон перед трансформацией (0.01° ≈ 1км)
    geom_dense = segmentize(geometry, max_segment_length=0.01)
    geom_sinu = shapely_transform(transformer.transform, geom_dense)

    # Пиксельные координаты bbox
    sx_min, sy_min, sx_max, sy_max = geom_sinu.bounds
    col_start = max(0, int((sx_min - x_min) / CELL_SIZE))
    col_end = min(cols, int((sx_max - x_min) / CELL_SIZE) + 1)
    row_start = max(0, int((y_max - sy_max) / CELL_SIZE))
    row_end = min(rows, int((y_max - sy_min) / CELL_SIZE) + 1)

    empty = {"total_pixels": 0, "valid_pixels": 0, "snow_pixels": 0,
             "water_pixels": 0, "sca_pct": None, "zones": []}
    if col_start >= col_end or row_start >= row_end:
        return empty

    subset = mosaic[row_start:row_end, col_start:col_end]
    n_rows_sub = row_end - row_start
    n_cols_sub = col_end - col_start

    # Координаты центров пикселей в Sinusoidal
    pixel_xs = x_min + (col_start + np.arange(n_cols_sub) + 0.5) * CELL_SIZE
    pixel_ys = y_max - (row_start + np.arange(n_rows_sub) + 0.5) * CELL_SIZE

    # Маска полигона (point-in-polygon)
    prepared_geom = prep(geom_sinu)
    poly_mask = np.zeros((n_rows_sub, n_cols_sub), dtype=bool)
    for r in range(n_rows_sub):
        for c in range(n_cols_sub):
            if prepared_geom.contains(Point(pixel_xs[c], pixel_ys[r])):
                poly_mask[r, c] = True

    # Индексы пикселей внутри полигона
    in_rows, in_cols = np.where(poly_mask)
    if len(in_rows) == 0:
        return empty

    # Координаты этих пикселей в Sinusoidal
    sinu_xs = pixel_xs[in_cols]
    sinu_ys = pixel_ys[in_rows]

    # --- Маска воды и высоты (через обратную проекцию → WGS84) ---
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

    # --- NDSI значения и классификация ---
    ndsi_values = subset[in_rows, in_cols].astype(np.float64)
    valid_ndsi = (ndsi_values >= 0) & (ndsi_values <= 100)
    not_water = ~is_water
    valid = valid_ndsi & not_water

    # Бинарная классификация: NDSI >= 40 = снег
    snow = (ndsi_values >= NDSI_THRESHOLD) & valid

    water_count = int(np.sum(is_water))
    valid_count = int(np.sum(valid))
    snow_count = int(np.sum(snow))
    sca_pct = round(snow_count / valid_count * 100, 2) if valid_count > 0 else None

    # --- Расчёт по высотным зонам ---
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
                    "valid_pixels": z_valid,
                    "snow_pixels": z_snow,
                    "sca_pct": z_sca,
                })

    return {
        "total_pixels": int(len(in_rows)),
        "valid_pixels": valid_count,
        "snow_pixels": snow_count,
        "water_pixels": water_count,
        "sca_pct": sca_pct,
        "zones": zones,
    }


def process_day(hdf_dir: str, shapefile_path: str, base_dir: str = "mod/base") -> list:
    """
    Обработка одного дня: мозаика → SCA для всех бассейнов.
    """
    print(f"\n{'='*60}")
    print(f"Обработка: {hdf_dir}")
    print(f"{'='*60}")

    # 1. Мозаика
    print("\n1. Мозаика тайлов...")
    mosaic, x_min, y_min, x_max, y_max = mosaic_tiles(hdf_dir)
    mosaic_bounds = (x_min, y_min, x_max, y_max)

    # 2. Загрузить бассейны из шейпфайла
    print("\n2. Загрузка бассейнов...")
    gdf = gpd.read_file(shapefile_path)
    if "PROCESS" in gdf.columns:
        gdf = gdf[gdf["PROCESS"] == 1]
    print(f"  Бассейнов (PROCESS=1): {len(gdf)}")

    # 3. Трансформеры
    sinu_crs = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext"
    transformer = Transformer.from_crs("EPSG:4326", sinu_crs, always_xy=True)
    inverse_transformer = Transformer.from_crs(sinu_crs, "EPSG:4326", always_xy=True)

    # 4. Расчёт SCA
    print(f"\n3. Расчёт SCA по бассейнам (NDSI >= {NDSI_THRESHOLD}, зоны {ZONE_EXTENT}м)...")
    base = Path(base_dir)
    results = []
    for _, row in gdf.iterrows():
        name = row.get("Name", "?")
        geom = row.geometry
        if geom is None:
            continue

        code = derive_code(name)

        # Загрузить маску воды
        water_mask_info = None
        wm_path = base / f"{code}_water_mask.asc"
        if wm_path.exists():
            try:
                water_mask_info = read_ascii_grid(str(wm_path))
            except (ValueError, IndexError):
                pass  # повреждённый файл, пропускаем

        # Загрузить DEM
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
            water_str = f"  water:{sca['water_pixels']}" if sca.get("water_pixels", 0) > 0 else ""
            zones_str = f"  ({len(sca['zones'])} зон)" if sca.get("zones") else ""
            print(f"  {name:<30} SCA: {sca['sca_pct']:>6.1f}%  "
                  f"(pixels: {sca['valid_pixels']}{water_str}){zones_str}")
        else:
            print(f"  {name:<30} нет данных")

    return results


def main():
    shapefile_path = Path("mod/base/ca_catchments.shp")
    base_dir = Path("mod/base")

    if not shapefile_path.exists():
        print(f"Шейпфайл {shapefile_path} не найден!")
        sys.exit(1)

    if len(sys.argv) > 1:
        hdf_dir = sys.argv[1]
    else:
        dirs = sorted(Path("modis_data").iterdir())
        if not dirs:
            print("Нет скачанных данных! Сначала запустите download_modis.py")
            sys.exit(1)
        hdf_dir = str(dirs[-1])

    results = process_day(hdf_dir, str(shapefile_path), str(base_dir))

    # Сохранить результаты
    date_str = Path(hdf_dir).name
    out_file = Path("output") / f"sca_{date_str}.json"
    out_file.parent.mkdir(exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nРезультаты: {out_file}")


if __name__ == "__main__":
    main()
