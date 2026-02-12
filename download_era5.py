"""
Скачивание ERA5-Land snow depth (глубина снежного покрова) для Центральной Азии.

ERA5-Land: ~9 км (0.1°) сетка, задержка ~5 дней.
Переменная: snow_depth (sde) — глубина снега в метрах.
"""

import logging
import sys
import zipfile
from pathlib import Path

import cdsapi

logger = logging.getLogger(__name__)

DEFAULT_BBOX = (55, 33, 85, 50)  # (west, south, east, north)


def parse_cdsapirc(path: str) -> dict:
    """Прочитать url и key из файла .cdsapirc."""
    config = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, value = line.partition(":")
                config[key.strip()] = value.strip()
    return config


def download_snow_depth(
    date_str: str,
    download_dir: str = "era5_data",
    bbox: tuple = DEFAULT_BBOX,
    cdsapirc_path: str = "config/.cdsapirc",
) -> Path:
    """
    Скачать ERA5-Land snow_depth за одну дату.

    Args:
        date_str: Дата в формате YYYY-MM-DD.
        download_dir: Базовая директория для сохранения.
        bbox: (west, south, east, north) — ограничивающий прямоугольник.
        cdsapirc_path: Путь к файлу с CDS API credentials.

    Returns:
        Path к скачанному NetCDF файлу.
    """
    rc = parse_cdsapirc(cdsapirc_path)
    url = rc.get("url")
    key = rc.get("key")
    if not url or not key:
        raise RuntimeError(f"Не найдены url/key в {cdsapirc_path}")

    client = cdsapi.Client(url=url, key=key)

    year, month, day = date_str.split("-")

    # CDS area: [north, west, south, east]
    west, south, east, north = bbox
    area = [north, west, south, east]

    out_dir = Path(download_dir) / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "snow_depth.nc"

    if out_path.exists():
        # Проверить что это действительно NetCDF, а не ZIP-остаток
        with open(out_path, "rb") as f:
            magic = f.read(4)
        if magic != b"PK\x03\x04":
            logger.info("ERA5 уже скачан: %s", out_path)
            return out_path
        # ZIP — удалить и скачать заново
        out_path.unlink()

    logger.info("Скачивание ERA5-Land snow_depth за %s...", date_str)

    download_target = out_dir / "snow_depth_raw"
    client.retrieve(
        "reanalysis-era5-land",
        {
            "variable": "snow_depth",
            "year": year,
            "month": month,
            "day": day,
            "time": "00:00",
            "area": area,
            "data_format": "netcdf",
        },
        str(download_target),
    )

    # CDS может вернуть ZIP — распаковать если нужно
    with open(download_target, "rb") as f:
        magic = f.read(4)

    if magic == b"PK\x03\x04":
        logger.info("Распаковка ZIP...")
        with zipfile.ZipFile(download_target, "r") as zf:
            nc_names = [n for n in zf.namelist() if n.endswith(".nc")]
            if not nc_names:
                raise RuntimeError(f"ZIP не содержит .nc файлов: {zf.namelist()}")
            zf.extract(nc_names[0], out_dir)
            extracted = out_dir / nc_names[0]
            extracted.rename(out_path)
        download_target.unlink()
    else:
        download_target.rename(out_path)

    size_mb = out_path.stat().st_size / 1024 / 1024
    logger.info("ERA5 скачан: %s (%.1f МБ)", out_path, size_mb)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if len(sys.argv) < 2:
        print("Usage: python download_era5.py YYYY-MM-DD")
        sys.exit(1)
    path = download_snow_depth(sys.argv[1])
    print(f"Downloaded: {path}")
