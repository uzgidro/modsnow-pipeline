"""
Скачивание MODIS MOD10A1F (Cloud-Gap-Filled Snow Cover) для Центральной Азии.

MOD10A1F — ежедневные данные с уже удалённой облачностью (не нужен алгоритм Gafurov).
Разрешение: 500м, проекция: Sinusoidal.
"""

import logging
import os
from pathlib import Path

import earthaccess

logger = logging.getLogger(__name__)

DEFAULT_BBOX = (55, 33, 85, 50)  # Центральная Азия: (west, south, east, north)


def login():
    """Авторизация в NASA Earthdata. Сначала env vars, потом .netrc."""
    username = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")

    if username and password:
        logger.info("Авторизация через переменные окружения...")
        auth = earthaccess.login(strategy="environment")
    else:
        logger.info("Авторизация через .netrc...")
        auth = earthaccess.login(persist=True)

    if not auth.authenticated:
        raise RuntimeError("Ошибка авторизации NASA Earthdata")
    return auth


def download_for_date(
    date_str: str,
    download_dir: str = "modis_data",
    bbox: tuple = DEFAULT_BBOX,
    product: str = "MOD10A1F",
    version: str = "61",
) -> Path:
    """
    Скачать все гранулы MODIS за дату для Центральной Азии.

    Returns:
        Path к директории с HDF файлами за этот день.

    Raises:
        RuntimeError: если данные не найдены или скачивание не удалось.
    """
    logger.info("Поиск %s за %s...", product, date_str)
    results = earthaccess.search_data(
        short_name=product,
        version=version,
        bounding_box=bbox,
        temporal=(date_str, date_str),
    )
    logger.info("Найдено гранул: %d", len(results))

    if not results:
        raise RuntimeError(f"Нет данных {product} за {date_str}")

    for r in results:
        umm = r.get("umm", {})
        logger.debug("  %s", umm.get("GranuleUR", "?"))

    day_dir = Path(download_dir) / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Скачивание в %s/ ...", day_dir)
    files = earthaccess.download(results, local_path=str(day_dir))

    if not files:
        raise RuntimeError(f"Скачивание не удалось для {date_str}")

    for f in files:
        p = Path(f)
        size_mb = p.stat().st_size / 1024 / 1024
        logger.info("  %s (%.1f МБ)", p.name, size_mb)

    return day_dir
