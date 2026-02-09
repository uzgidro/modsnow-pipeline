"""
Обработка MODIS MOD10A1F: мозаика тайлов → расчёт SCA по бассейнам.

Пайплайн:
  1. Чтение HDF тайлов (CGF_NDSI_Snow_Cover)
  2. Мозаика тайлов в единый растр
  3. Репроекция из Sinusoidal → WGS84
  4. Клиппинг по полигонам бассейнов (GeoJSON)
  5. Расчёт % снежного покрова (SCA) для каждого бассейна
"""

import glob
import json
import sys
from pathlib import Path

import geopandas as gpd
import netCDF4
import numpy as np
from pyproj import Transformer
from shapely import segmentize
from shapely.geometry import box, Point
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
) -> dict:
    """
    Рассчитать SCA (Snow Cover Area %) для одного бассейна.
    Использует полигонную маску (point-in-polygon для центров пикселей).
    SCA = mean(NDSI) по всем валидным пикселям внутри полигона.

    Возвращает: {total_pixels, valid_pixels, snow_pixels, sca_pct}
    """
    x_min, y_min, x_max, y_max = mosaic_bounds
    rows, cols = mosaic.shape

    # Уплотнить полигон перед трансформацией (0.01° ≈ 1км)
    # чтобы рёбра корректно проецировались из WGS84 в Sinusoidal
    geom_dense = segmentize(geometry, max_segment_length=0.01)

    # Трансформировать полигон из WGS84 в Sinusoidal
    geom_sinu = shapely_transform(transformer.transform, geom_dense)

    # Bbox трансформированного полигона в Sinusoidal
    sx_min, sy_min, sx_max, sy_max = geom_sinu.bounds

    # Пиксельные координаты bbox
    col_start = max(0, int((sx_min - x_min) / CELL_SIZE))
    col_end = min(cols, int((sx_max - x_min) / CELL_SIZE) + 1)
    row_start = max(0, int((y_max - sy_max) / CELL_SIZE))
    row_end = min(rows, int((y_max - sy_min) / CELL_SIZE) + 1)

    if col_start >= col_end or row_start >= row_end:
        return {"total_pixels": 0, "valid_pixels": 0, "snow_pixels": 0, "sca_pct": None}

    # Вырезать подмассив
    subset = mosaic[row_start:row_end, col_start:col_end]

    # Создать маску полигона: проверить центр каждого пикселя
    n_rows_sub = row_end - row_start
    n_cols_sub = col_end - col_start

    # Координаты центров пикселей в Sinusoidal
    pixel_xs = x_min + (col_start + np.arange(n_cols_sub) + 0.5) * CELL_SIZE
    pixel_ys = y_max - (row_start + np.arange(n_rows_sub) + 0.5) * CELL_SIZE

    # Prepared geometry для быстрого point-in-polygon
    prepared_geom = prep(geom_sinu)

    # Построить маску: True если центр пикселя внутри полигона
    poly_mask = np.zeros((n_rows_sub, n_cols_sub), dtype=bool)
    for r in range(n_rows_sub):
        for c in range(n_cols_sub):
            if prepared_geom.contains(Point(pixel_xs[c], pixel_ys[r])):
                poly_mask[r, c] = True

    # Применить маску полигона
    valid = (subset >= 0) & (subset <= 100) & poly_mask
    snow = (subset > 0) & (subset <= 100) & poly_mask

    total = int(np.sum(poly_mask))
    valid_count = int(np.sum(valid))
    snow_count = int(np.sum(snow))

    # SCA = mean(FSC) по всем валидным пикселям
    # FSC (Fractional Snow Cover) по формуле Salomonson & Appel (2004):
    #   FSC = -0.01 + 1.45 * NDSI, where NDSI in [0,1]
    if valid_count > 0:
        ndsi_values = subset[valid].astype(np.float64) / 100.0
        fsc = np.clip(-0.01 + 1.45 * ndsi_values, 0.0, 1.0)
        sca_pct = round(float(np.mean(fsc) * 100), 2)
    else:
        sca_pct = None

    return {
        "total_pixels": total,
        "valid_pixels": valid_count,
        "snow_pixels": snow_count,
        "sca_pct": sca_pct,
    }


def process_day(hdf_dir: str, geojson_path: str) -> list:
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

    # 2. Загрузить GeoJSON
    print("\n2. Загрузка бассейнов...")
    gdf = gpd.read_file(geojson_path)
    print(f"  Бассейнов: {len(gdf)}")

    # 3. Трансформер WGS84 → Sinusoidal
    transformer = Transformer.from_crs(
        "EPSG:4326",
        "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext",
        always_xy=True,
    )

    # 4. Расчёт SCA
    print("\n3. Расчёт SCA по бассейнам...")
    results = []
    for _, row in gdf.iterrows():
        name = row["properties"]["Name"] if "properties" in gdf.columns else row.get("Name", "?")
        # Handle nested properties from GeoJSON
        if hasattr(row, "geometry"):
            geom = row.geometry
        else:
            continue

        sca = calc_sca_for_catchment(mosaic, mosaic_bounds, geom, transformer)
        sca["name"] = name
        results.append(sca)

        if sca["sca_pct"] is not None:
            print(f"  {name:<30} SCA: {sca['sca_pct']:>6.1f}%  (pixels: {sca['valid_pixels']})")
        else:
            print(f"  {name:<30} нет данных")

    return results


def main():
    geojson_path = "catchments.geojson"
    if not Path(geojson_path).exists():
        print(f"Файл {geojson_path} не найден!")
        print("Сначала запустите parser.py для извлечения GeoJSON из бандла.")
        sys.exit(1)

    if len(sys.argv) > 1:
        hdf_dir = sys.argv[1]
    else:
        # Найти последнюю скачанную дату
        dirs = sorted(Path("modis_data").iterdir())
        if not dirs:
            print("Нет скачанных данных! Сначала запустите download_modis.py")
            sys.exit(1)
        hdf_dir = str(dirs[-1])

    results = process_day(hdf_dir, geojson_path)

    # Сохранить результаты
    date_str = Path(hdf_dir).name
    out_file = Path("output") / f"sca_{date_str}.json"
    out_file.parent.mkdir(exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nРезультаты: {out_file}")


if __name__ == "__main__":
    main()
