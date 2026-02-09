"""
Настройка NASA Earthdata и тестовое скачивание MODIS MOD10A1.

Шаг 1: Авторизация (сохраняет токен в ~/.netrc)
Шаг 2: Поиск данных MOD10A1 за последний день
Шаг 3: Скачивание тестового тайла
"""

import earthaccess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DOWNLOAD_DIR = Path("modis_data")


def setup_auth():
    """Авторизация в NASA Earthdata."""
    print("=" * 60)
    print("Авторизация NASA Earthdata")
    print("=" * 60)

    auth = earthaccess.login(persist=True)
    if auth.authenticated:
        print("Авторизация успешна!")
        return True
    else:
        print("Ошибка авторизации.")
        return False


def search_modis(date_str: str = None, bbox: tuple = None):
    """
    Поиск MODIS MOD10A1 гранул.

    bbox: (west, south, east, north) — Центральная Азия по умолчанию
    date_str: дата в формате YYYY-MM-DD (по умолчанию — вчера)
    """
    if bbox is None:
        # Центральная Азия: примерный охват
        bbox = (55, 33, 85, 50)

    if date_str is None:
        # Вчерашний день (данные MODIS задерживаются на 1-2 дня)
        dt = datetime.now() - timedelta(days=3)
        date_str = dt.strftime("%Y-%m-%d")

    print(f"\nПоиск MOD10A1 за {date_str}")
    print(f"Регион: {bbox}")

    results = earthaccess.search_data(
        short_name="MOD10A1",
        version="061",
        bounding_box=bbox,
        temporal=(date_str, date_str),
    )

    print(f"Найдено гранул: {len(results)}")
    for i, granule in enumerate(results):
        umm = granule.get("umm", {})
        granule_id = umm.get("GranuleUR", "?")
        print(f"  {i + 1}. {granule_id}")

    return results


def download_test(results, max_granules: int = 1):
    """Скачать тестовую гранулу."""
    if not results:
        print("Нет данных для скачивания.")
        return

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    print(f"\nСкачивание {max_granules} гранул в {DOWNLOAD_DIR}/...")

    files = earthaccess.download(
        results[:max_granules],
        local_path=str(DOWNLOAD_DIR),
    )

    print(f"\nСкачано файлов: {len(files)}")
    for f in files:
        p = Path(f)
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  {p.name} ({size_mb:.1f} МБ)")

    return files


def main():
    # 1. Авторизация
    if not setup_auth():
        sys.exit(1)

    # 2. Поиск
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    results = search_modis(date_str=date_str)

    # 3. Тестовое скачивание
    if results:
        answer = input("\nСкачать 1 тестовую гранулу? [y/n]: ").strip().lower()
        if answer == "y":
            download_test(results, max_granules=1)


if __name__ == "__main__":
    main()
