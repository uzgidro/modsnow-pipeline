"""
Скачивание MODIS MOD10A1F (Cloud-Gap-Filled Snow Cover) для Центральной Азии.

MOD10A1F — ежедневные данные с уже удалённой облачностью (не нужен алгоритм Gafurov).
Разрешение: 500м, проекция: Sinusoidal.
"""

import earthaccess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DOWNLOAD_DIR = Path("modis_data")

# Центральная Азия: bbox (west, south, east, north)
CA_BBOX = (55, 33, 85, 50)


def login():
    auth = earthaccess.login(persist=True)
    if not auth.authenticated:
        print("Ошибка авторизации NASA Earthdata!")
        sys.exit(1)
    return auth


def search_granules(date_str: str, product: str = "MOD10A1F"):
    """Поиск гранул за конкретную дату."""
    results = earthaccess.search_data(
        short_name=product,
        version="61",
        bounding_box=CA_BBOX,
        temporal=(date_str, date_str),
    )
    return results


def download_day(date_str: str, product: str = "MOD10A1F"):
    """Скачать все гранулы за день для Центральной Азии."""
    print(f"\nПоиск {product} за {date_str}...")
    results = search_granules(date_str, product)
    print(f"Найдено гранул: {len(results)}")

    if not results:
        return []

    # Показать тайлы
    for r in results:
        umm = r.get("umm", {})
        print(f"  {umm.get('GranuleUR', '?')}")

    day_dir = DOWNLOAD_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nСкачивание в {day_dir}/...")
    files = earthaccess.download(results, local_path=str(day_dir))
    print(f"Скачано: {len(files)} файлов")
    for f in files:
        p = Path(f)
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  {p.name} ({size_mb:.1f} МБ)")

    return files


def main():
    login()

    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        # 3 дня назад (задержка MODIS)
        dt = datetime.now() - timedelta(days=3)
        date_str = dt.strftime("%Y-%m-%d")

    download_day(date_str)


if __name__ == "__main__":
    main()
