"""
Сравнение наших расчётов SCA с данными MODSNOW (Firebase).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from parser import ModsnowParser


def load_our_results(date_str: str) -> dict:
    """Загрузить наши результаты из JSON."""
    path = Path("output") / f"sca_{date_str}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {r["name"]: r["sca_pct"] for r in data if r["sca_pct"] is not None}


def load_firebase_data(date_str: str) -> dict:
    """Загрузить данные из Firebase для всех рек на конкретную дату."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.year
    doy = (dt - datetime(year, 1, 1)).days + 1

    print(f"Firebase: загрузка данных за {date_str} (год={year}, день={doy})...")

    results = {}
    with ModsnowParser() as p:
        p.load_index()
        for river in p.list_rivers():
            name = river["name"]
            records = p.fetch_snow_cover_data(name)
            if not records:
                continue
            for rec in records:
                if rec["year"] == year and rec["doy"] == doy and rec["snow_pct"] != -9:
                    results[name] = rec["snow_pct"]
                    break

    return results


def normalize_name(name: str) -> str:
    """Нормализовать имя для сопоставления."""
    return name.lower().replace("-", "_").replace(" ", "_")


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2025-12-01"

    print(f"Сравнение SCA на {date_str}")
    print("=" * 75)

    our = load_our_results(date_str)
    firebase = load_firebase_data(date_str)

    # Нормализованные маппинги
    our_norm = {normalize_name(k): (k, v) for k, v in our.items()}
    fb_norm = {normalize_name(k): (k, v) for k, v in firebase.items()}

    # Найти пересечения
    common_keys = set(our_norm.keys()) & set(fb_norm.keys())

    print(f"\nНаших бассейнов: {len(our)}")
    print(f"Firebase рек:    {len(firebase)}")
    print(f"Совпадений:      {len(common_keys)}")

    print(f"\n{'Бассейн':<28} {'Наш SCA%':>10} {'Firebase%':>10} {'Разница':>10}")
    print("-" * 62)

    diffs = []
    for key in sorted(common_keys):
        our_name, our_val = our_norm[key]
        fb_name, fb_val = fb_norm[key]
        diff = our_val - fb_val
        diffs.append(abs(diff))
        marker = " " if abs(diff) < 5 else " *" if abs(diff) < 15 else " **"
        print(f"  {our_name:<26} {our_val:>8.1f}% {fb_val:>8.1f}% {diff:>+8.1f}%{marker}")

    if diffs:
        print(f"\n{'Статистика расхождений':}")
        print(f"  Среднее:    {sum(diffs)/len(diffs):.1f}%")
        print(f"  Медиана:    {sorted(diffs)[len(diffs)//2]:.1f}%")
        print(f"  Макс:       {max(diffs):.1f}%")
        print(f"  < 5%:       {sum(1 for d in diffs if d < 5)}/{len(diffs)}")
        print(f"  < 10%:      {sum(1 for d in diffs if d < 10)}/{len(diffs)}")

    # Сохранить
    out_path = Path("output") / f"compare_{date_str}.json"
    comparison = []
    for key in sorted(common_keys):
        our_name, our_val = our_norm[key]
        fb_name, fb_val = fb_norm[key]
        comparison.append({
            "name": our_name,
            "our_sca": our_val,
            "firebase_sca": fb_val,
            "diff": round(our_val - fb_val, 2),
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"\nСохранено: {out_path}")


if __name__ == "__main__":
    main()
