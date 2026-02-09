"""Диагностика поиска MODIS MOD10A1."""

import earthaccess

auth = earthaccess.login(persist=True)
if not auth.authenticated:
    print("Ошибка авторизации!")
    exit(1)
print("Авторизация OK")

bbox = (55, 33, 85, 50)

tests = [
    {"short_name": "MOD10A1", "version": "61"},
    {"short_name": "MOD10A1F", "version": "61"},
    {"short_name": "MOD10C1", "version": "61"},
]

for t in tests:
    print(f"\n--- {t['short_name']} v{t['version']} ---")
    try:
        results = earthaccess.search_data(
            short_name=t["short_name"],
            version=t["version"],
            bounding_box=bbox,
            temporal=("2025-12-01", "2025-12-05"),
        )
        print(f"  Найдено: {len(results)}")
        if results:
            umm = results[0].get("umm", {})
            print(f"  Пример: {umm.get('GranuleUR', '?')}")
    except Exception as e:
        print(f"  Ошибка: {e}")

# Если ничего — попробуем без bbox
print("\n--- MOD10A1 v61 БЕЗ bbox ---")
try:
    results = earthaccess.search_data(
        short_name="MOD10A1",
        version="61",
        temporal=("2025-12-01", "2025-12-01"),
        count=5,
    )
    print(f"  Найдено: {len(results)}")
    if results:
        umm = results[0].get("umm", {})
        print(f"  Пример: {umm.get('GranuleUR', '?')}")
except Exception as e:
    print(f"  Ошибка: {e}")

# Попробуем point вместо bbox
print("\n--- MOD10A1 v61 point=(68,41) Ташкент ---")
try:
    results = earthaccess.search_data(
        short_name="MOD10A1",
        version="61",
        point=(68, 41),
        temporal=("2025-12-01", "2025-12-01"),
    )
    print(f"  Найдено: {len(results)}")
    if results:
        umm = results[0].get("umm", {})
        print(f"  Пример: {umm.get('GranuleUR', '?')}")
except Exception as e:
    print(f"  Ошибка: {e}")
