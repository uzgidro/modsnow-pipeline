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


def _reissue_token_from_credentials():
    """Принудительно перевыпустить токен из логина/пароля (env).

    earthaccess.__auth__.login() рано выходит, если authenticated уже взведён
    (со старым токеном). Сбрасываем флаг и логинимся штатным earthaccess.login(),
    который идёт в _find_or_create_token() (EDL находит валидный токен или создаёт
    новый) и пересоздаёт __store__. Не требует доступа к .netrc.
    """
    earthaccess.__auth__.authenticated = False
    return earthaccess.login(strategy="environment", persist=True)


def login():
    """Авторизация в NASA Earthdata. Сначала env vars, потом .netrc.

    Если закэшированный токен протух (auth.authenticated == False), пробуем
    принудительно перевыпустить его из логина/пароля (env). Это не требует
    доступа к серверу с .netrc — достаточно EARTHDATA_USERNAME/PASSWORD.
    """
    username = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")
    has_credentials = bool(username and password)

    if has_credentials:
        logger.info("Авторизация через переменные окружения...")
        auth = earthaccess.login(strategy="environment", persist=True)
    else:
        logger.info("Авторизация через .netrc...")
        auth = earthaccess.login(persist=True)

    if auth.authenticated:
        return auth

    # Кэш/токен невалиден. Перевыпускаем токен, если есть логин/пароль.
    if has_credentials:
        logger.warning("Токен невалиден — перевыпускаем из логина/пароля...")
        try:
            auth = _reissue_token_from_credentials()
        except Exception:
            logger.exception("Не удалось перевыпустить токен Earthdata")

    if not auth.authenticated:
        raise RuntimeError(
            "Ошибка авторизации NASA Earthdata. Проверьте "
            "EARTHDATA_USERNAME/EARTHDATA_PASSWORD или ~/.netrc."
        )
    return auth


def download_for_date(
    date_str: str,
    download_dir: str = "modis_data",
    bbox: tuple = DEFAULT_BBOX,
    product: str = "MOD10A1F",
    version: str = "61",
) -> Path | None:
    """
    Скачать все гранулы MODIS за дату для Центральной Азии.

    Returns:
        Path к директории с HDF файлами за этот день, или None если данных нет.

    Raises:
        RuntimeError: если скачивание не удалось.
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
        logger.warning("Нет данных %s за %s", product, date_str)
        return None

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
