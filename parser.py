"""
MODSNOW Site Parser — парсер данных снежного покрова с modsnow.online

Источник данных: Firebase Realtime Database (modsnow-a1c82)
Данные: MODIS MOD10A1 snow cover, Центральная Азия, с 2000 года

Файлы для каждой реки/бассейна:
  1.png  — карта Snow Cover Area
  2.jpeg — график Snow Cover Dynamics
  3.png  — дополнительная карта/график
  4.txt  — дневные данные: год; день_года; облачность%; снежный_покров%
  5.txt  — данные по зонам высот: год  день  z1  z2  z3  z4  z5  z6
"""

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

# === Конфигурация ===
FIREBASE_DB_URL = "https://modsnow-a1c82-default-rtdb.firebaseio.com"
OUTPUT_DIR = Path("output")

# 49 рек, зашитых в приложении
KNOWN_RIVERS = [
    "ahangaran_irtash",
    "akdarya_gissarak",
    # "Ala_archa",
    # "amudarya_kerky",
    # "Angren",
    # "Atrek",
    "Big_Naryn",
    # "chadak_djulaysay",
    "Chatkal_Hudaydodsay",
    "Chirchik",
    # "chu_kochkor",
    # "fergana_valley",
    # "gavasay_gava",
    # "Gunt_Khorog",
    # "kafirnigan_tartki",
    # "karadarya",
    "Karadaryo_Andijan",
    # "kashkadarya",
    # "kashkadarya_chirakchi",
    # "kashkadarya_varganza",
    # "kashkadarye_varganza",
    # "kashkadaryo_chirakchi",
    # "Koksu",
    # "malaya_almatinka",
    # "maydantal",
    # "murgab",
    # "Murgob_Tagtabazar",
    "naryn",
    "oygaing",
    # "pachkamar",
    # "packhamar",
    # "pandj",
    "piskem_mullala",
    # "sangardak_kinguzar",
    # "sangzar_kirk",
    # "small_naryn",
    "sox_sarykanda",
    # "Sumbar_Magtimgulli",
    # "Surkhandarya",
    # "talas_klyuchovka",
    # "Tedjen_Pulhatyn",
    "tupalang_zarchob",
    "Ugam",
    # "vanch",
    # "Varzob_Dagana",
    # "Wachsh_Darband",
    # "yakarcha",
    # "yakkabag_tatar",
    "zerafshan_dupuli",
]


def doy_to_date(year: int, doy: int) -> str:
    """Конвертирует год + день года в дату YYYY-MM-DD."""
    try:
        dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return f"{year}-DOY{doy}"


class ModsnowParser:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.client = httpx.Client(timeout=30, follow_redirects=True)
        self._river_folders: dict = {}
        self._river_files: dict = {}

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Firebase API ---

    def _fetch_firebase(self, path: str) -> dict:
        """Получить данные из Firebase RTDB."""
        url = f"{FIREBASE_DB_URL}/{path}.json"
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.json() or {}

    def load_index(self):
        """Загрузить индекс рек (RiverFolder + RiverFile)."""
        print("Загрузка индекса рек из Firebase...")
        self._river_folders = self._fetch_firebase("RiverFolder")
        self._river_files = self._fetch_firebase("RiverFile")
        print(f"  Найдено папок (рек): {len(self._river_folders)}")
        print(f"  Найдено файлов: {len(self._river_files)}")

    def list_rivers(self) -> list[dict]:
        """Список всех рек с метаданными."""
        if not self._river_folders:
            self.load_index()

        rivers = []
        for folder_id, folder in self._river_folders.items():
            title = folder.get("Title", "")
            # Извлечь имя реки (убрать "River " префикс)
            name = title.replace("River ", "") if title.startswith("River ") else title
            rivers.append({
                "id": folder_id,
                "title": title,
                "name": name,
                "created_at": folder.get("CreatedAt", folder.get("CreatedOn", "")),
                "cover_photo_url": folder.get("CoverPhotoUrl", ""),
            })
        return sorted(rivers, key=lambda r: r["name"].lower())

    def _get_river_folder_id(self, river_name: str) -> Optional[str]:
        """Найти folder_id реки по имени."""
        name_lower = river_name.lower().replace(" ", "_")
        for folder_id, folder in self._river_folders.items():
            title = folder.get("Title", "")
            folder_name = title.lower().replace("river ", "").replace(" ", "_")
            if folder_name == name_lower:
                return folder_id
        return None

    def _get_river_files(self, folder_id: str) -> dict[str, dict]:
        """Получить файлы реки по folder_id. Возвращает {filename: file_data}."""
        files = {}
        for file_id, file_data in self._river_files.items():
            if file_data.get("RiverId") == folder_id:
                fname = file_data.get("FileName", "")
                files[fname] = file_data
        return files

    # --- Парсинг данных снежного покрова ---

    def fetch_snow_cover_data(self, river_name: str) -> Optional[list[dict]]:
        """
        Получить данные снежного покрова (4.txt) для реки.
        Формат: год; день_года; облачность%; снежный_покров%
        Возвращает список словарей с полями:
          year, doy, date, cloud_pct, snow_pct
        """
        if not self._river_folders:
            self.load_index()

        folder_id = self._get_river_folder_id(river_name)
        if not folder_id:
            print(f"  Река '{river_name}' не найдена")
            return None

        files = self._get_river_files(folder_id)
        file_data = files.get("4.txt")
        if not file_data:
            print(f"  Файл 4.txt не найден для '{river_name}'")
            return None

        url = file_data["FileUrl"]
        print(f"  Загрузка данных: {river_name} (4.txt)...")
        resp = self.client.get(url)
        resp.raise_for_status()

        records = []
        for line in resp.text.strip().split("\n"):
            parts = [p.strip().rstrip(";") for p in line.split(";")]
            if len(parts) < 4:
                continue
            try:
                year = int(parts[0])
                doy = int(parts[1])
                cloud = float(parts[2])
                snow = float(parts[3])
                if cloud == -9 or snow == -9:
                    continue  # нет данных
                records.append({
                    "year": year,
                    "doy": doy,
                    "date": doy_to_date(year, doy),
                    "cloud_pct": cloud,
                    "snow_pct": snow,
                })
            except (ValueError, IndexError):
                continue

        print(
            f"  Загружено {len(records)} записей ({records[0]['date']} - {records[-1]['date']})" if records else "  Нет данных")
        return records

    def fetch_zone_data(self, river_name: str) -> Optional[list[dict]]:
        """
        Получить данные по зонам высот (5.txt) для реки.
        Формат: год  день  z1  z2  ...  zN  (от 1 до 14 зон)
        Возвращает список словарей с полями:
          year, doy, date, zone1..zoneN
        """
        if not self._river_folders:
            self.load_index()

        folder_id = self._get_river_folder_id(river_name)
        if not folder_id:
            print(f"  Река '{river_name}' не найдена")
            return None

        files = self._get_river_files(folder_id)
        file_data = files.get("5.txt")
        if not file_data:
            print(f"  Файл 5.txt не найден для '{river_name}'")
            return None

        url = file_data["FileUrl"]
        print(f"  Загрузка данных: {river_name} (5.txt)...")
        resp = self.client.get(url)
        resp.raise_for_status()

        records = []
        num_zones = 0
        for line in resp.text.strip().split("\n"):
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                year = int(parts[0])
                doy = int(parts[1])
                zones = [float(p) for p in parts[2:]]
                num_zones = max(num_zones, len(zones))
                record = {
                    "year": year,
                    "doy": doy,
                    "date": doy_to_date(year, doy),
                }
                for i, val in enumerate(zones, 1):
                    record[f"zone{i}"] = val
                records.append(record)
            except (ValueError, IndexError):
                continue

        if records:
            print(f"  Загружено {len(records)} записей, {num_zones} зон ({records[0]['date']} - {records[-1]['date']})")
        else:
            print("  Нет данных")
        return records

    # --- Скачивание изображений ---

    def download_image(self, river_name: str, image_type: str = "snow_area") -> Optional[str]:
        """
        Скачать изображение для реки.
        image_type: 'snow_area' (1.png), 'dynamics' (2.jpeg), 'map' (3.png)
        """
        if not self._river_folders:
            self.load_index()

        folder_id = self._get_river_folder_id(river_name)
        if not folder_id:
            print(f"  Река '{river_name}' не найдена")
            return None

        files = self._get_river_files(folder_id)
        file_map = {"snow_area": "1.png", "dynamics": "2.jpeg", "map": "3.png"}
        fname = file_map.get(image_type)
        if not fname:
            print(f"  Неизвестный тип: {image_type}")
            return None

        file_data = files.get(fname)
        if not file_data:
            print(f"  Файл {fname} не найден для '{river_name}'")
            return None

        url = file_data["FileUrl"]
        river_dir = self.output_dir / river_name.lower().replace(" ", "_")
        river_dir.mkdir(exist_ok=True)
        out_path = river_dir / fname

        print(f"  Скачивание {fname} для '{river_name}'...")
        resp = self.client.get(url)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        print(f"  Сохранено: {out_path}")
        return str(out_path)

    # --- Экспорт данных ---

    def save_snow_csv(self, river_name: str, records: list[dict], suffix: str = "snow"):
        """Сохранить данные снежного покрова в CSV."""
        river_dir = self.output_dir / river_name.lower().replace(" ", "_")
        river_dir.mkdir(exist_ok=True)
        out_path = river_dir / f"{suffix}.csv"

        if not records:
            return

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        print(f"  CSV: {out_path} ({len(records)} строк)")

    def save_json(self, river_name: str, data: dict, filename: str = "data.json"):
        """Сохранить данные в JSON."""
        river_dir = self.output_dir / river_name.lower().replace(" ", "_")
        river_dir.mkdir(exist_ok=True)
        out_path = river_dir / filename

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  JSON: {out_path}")

    # --- Полный парсинг реки ---

    def parse_river(self, river_name: str, download_images: bool = True):
        """Полный парсинг одной реки: данные + изображения."""
        print(f"\n{'=' * 60}")
        print(f"Река: {river_name}")
        print(f"{'=' * 60}")

        # Данные снежного покрова
        snow_data = self.fetch_snow_cover_data(river_name)
        if snow_data:
            self.save_snow_csv(river_name, snow_data, "snow_cover")
            # Последние данные
            latest = snow_data[-1]
            print(f"  Последние данные: {latest['date']} — снег: {latest['snow_pct']}%")

        # Данные по зонам
        zone_data = self.fetch_zone_data(river_name)
        if zone_data:
            self.save_snow_csv(river_name, zone_data, "zone_data")

        # Изображения
        if download_images:
            for img_type in ["snow_area", "dynamics", "map"]:
                self.download_image(river_name, img_type)

        # Сводка в JSON
        summary = {
            "river": river_name,
            "parsed_at": datetime.now().isoformat(),
            "snow_cover_records": len(snow_data) if snow_data else 0,
            "zone_records": len(zone_data) if zone_data else 0,
            "latest_snow": snow_data[-1] if snow_data else None,
            "latest_zone": zone_data[-1] if zone_data else None,
        }
        self.save_json(river_name, summary, "summary.json")
        return summary

    def get_latest_snow(self, river_name: str) -> Optional[dict]:
        """Быстро получить последние данные по снежному покрову."""
        if not self._river_folders:
            self.load_index()

        snow = self.fetch_snow_cover_data(river_name)
        if not snow:
            return None

        # Найти последнюю валидную запись
        for record in reversed(snow):
            if record["snow_pct"] != -9:
                return record
        return None


def print_rivers_table(rivers: list[dict]):
    """Вывести таблицу рек."""
    print(f"\n{'#':<4} {'Имя':<30} {'Страна/Регион':<20}")
    print("-" * 54)
    for i, r in enumerate(rivers, 1):
        print(f"{i:<4} {r['name']:<30}")


def main():
    print("=" * 60)
    print("MODSNOW Parser — Данные снежного покрова Центральной Азии")
    print("=" * 60)

    with ModsnowParser() as parser:
        # Загрузить индекс
        rivers = parser.list_rivers()
        print_rivers_table(rivers)

        # Интерактивный выбор
        print(f"\nВсего доступно рек: {len(rivers)}")
        print("\nВведите имена рек через запятую (или 'all' для всех):")
        print("Пример: Chirchik, naryn, Ugam")

        if len(sys.argv) > 1:
            selection = " ".join(sys.argv[1:])
        else:
            selection = input("> ").strip()

        if not selection:
            print("Ничего не выбрано.")
            return

        if selection.lower() == "all":
            selected = [r["name"] for r in rivers]
        else:
            selected = [s.strip() for s in selection.split(",")]

        # Парсить выбранные реки
        results = []
        for river_name in selected:
            try:
                result = parser.parse_river(river_name)
                results.append(result)
            except Exception as e:
                print(f"  ОШИБКА: {e}")

        # Итоговая сводка
        print(f"\n{'=' * 60}")
        print("ИТОГО")
        print(f"{'=' * 60}")
        for r in results:
            if r and r.get("latest_snow"):
                ls = r["latest_snow"]
                print(f"  {r['river']:<25} {ls['date']}  снег: {ls['snow_pct']:>6.1f}%")


if __name__ == "__main__":
    main()
