# Plan: Docker Deployment + Autonomous Pipeline

## Context
MODIS SCA pipeline работает локально: скачивает MOD10A1F, считает SCA по 10 водосборам с NDSI>=40, высотными зонами и водными масками. Нужно подготовить к автономной работе в Docker: скачивание за (today-3) → обработка → POST на REST API → удаление HDF файлов. CI/CD через GitHub Actions → Docker Hub. Firebase данные НЕ нужны.

## Final Project Structure

```
modsnow-site-parser/
├── data/                           # Base data (~50MB, tracked in git)
│   ├── ca_catchments.shp/shx/dbf/cpg/prj
│   ├── {code}_dem500m.asc          # 10 DEM files
│   └── {code}_water_mask.asc       # 10 water mask files
├── config/
│   └── config.yaml                 # Configuration template
├── .github/workflows/
│   └── docker-publish.yml          # CI/CD: build + push to Docker Hub
├── download_modis.py               # Download module (MODIFIED)
├── process_modis.py                # Processing module (MODIFIED)
├── run.py                          # Orchestrator + scheduler (NEW)
├── api_client.py                   # REST API client (NEW)
├── requirements.txt                # Dependencies (NEW)
├── Dockerfile                      # (NEW)
├── docker-compose.yml              # (NEW)
├── .dockerignore                   # (NEW)
└── .gitignore                      # (UPDATED)
```

## Implementation Steps

### Step 1: Create `data/` — copy base files from `mod/base/`

Copy 25 files (~50MB):
- `ca_catchments.shp`, `.shx`, `.dbf`, `.cpg`, `.prj`
- 10x `{code}_dem500m.asc`
- 10x `{code}_water_mask.asc`

НЕ копировать: `ca_dem500m.asc` (221MB), `correls_month/` (317MB), `.aux.xml`, `.qpj`, `.shp.xml`

### Step 2: Modify `process_modis.py`

- Default `data_dir` = `"data"` вместо `"mod/base"`
- Убрать из вывода: `total_pixels`, `valid_pixels`, `snow_pixels`, `water_pixels`
- Убрать из зон: `valid_pixels`, `snow_pixels`
- Оставить: `{"name", "sca_pct", "zones": [{"min_elev", "max_elev", "sca_pct"}]}`
- Заменить `print()` на `logging`
- Убрать `main()` / `if __name__` → модуль-библиотека
- Убрать запись в `output/` (результат возвращается из `process_day()`)

### Step 3: Modify `download_modis.py`

- Новая функция `download_for_date(date_str, download_dir, bbox, product, version) -> Path`
- Логин: сначала env vars (`EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD`), потом `.netrc`
- Заменить `print()` на `logging`, `sys.exit()` на exceptions
- Убрать `main()` / `if __name__` → модуль-библиотека

### Step 4: Create `api_client.py`

```python
def send_results(payload: dict, api_config: dict) -> bool:
```
- POST JSON на `api_config["url"]`
- Headers: `Authorization: Bearer {api_key}` если задан
- Retry: 3 попытки с exponential backoff (2s, 4s, 8s)
- Return True/False

### Step 5: Create `config/config.yaml`

```yaml
api:
  url: "https://example.com/api/snow-cover"
  timeout: 30
  retries: 3
  # api_key: "..."

schedule:
  time: "06:00"  # UTC

modis:
  days_behind: 3
  bbox: [55, 33, 85, 50]
  product: "MOD10A1F"
  version: "61"

paths:
  data_dir: "data"
  download_dir: "modis_data"

logging:
  level: "INFO"
```

Путь к конфигу: env `CONFIG_PATH` или `config/config.yaml` по умолчанию.

### Step 6: Create `run.py` — orchestrator

Основной entry point. Логика:

```
main():
  1. load_config() из YAML
  2. setup_logging()
  3. CLI аргументы:
     --once          → run_pipeline() один раз и выйти
     2026-02-06      → run_pipeline_for_date() и выйти
     (без аргументов) → запуск на startup + APScheduler ежедневно
  4. signal handlers (SIGTERM/SIGINT) → graceful shutdown

run_pipeline(config):
  1. date = today - days_behind
  2. download_for_date(date) → hdf_dir
  3. process_day(hdf_dir, data_dir) → results
  4. payload = {"date": date, "catchments": results}
  5. send_results(payload, api_config) → success
  6. if success: cleanup (delete *.hdf, *.hdf.xml, rmdir)
     else: keep files, log warning
```

APScheduler v3 (BlockingScheduler + CronTrigger), `misfire_grace_time=3600`.

### Step 7: Create `requirements.txt`

```
numpy>=2.0
netCDF4>=1.7
geopandas>=1.0
pyproj>=3.6
shapely>=2.0
earthaccess>=0.12
APScheduler>=3.10,<4.0
requests>=2.31
PyYAML>=6.0
```

### Step 8: Create `Dockerfile`

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY data/ /app/data/
COPY config/ /app/config/
COPY download_modis.py process_modis.py run.py api_client.py ./
RUN mkdir -p /app/modis_data
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import os; assert os.path.exists('/app/data/ca_catchments.shp')"
CMD ["python", "run.py"]
```

### Step 9: Create `docker-compose.yml`

```yaml
services:
  modsnow-pipeline:
    build: .
    image: modsnow-pipeline:latest
    container_name: modsnow-pipeline
    restart: unless-stopped
    environment:
      - EARTHDATA_USERNAME=${EARTHDATA_USERNAME}
      - EARTHDATA_PASSWORD=${EARTHDATA_PASSWORD}
    volumes:
      - ./config/config.yaml:/app/config/config.yaml:ro
    stop_grace_period: 5m
```

`.env` файл (не в git): `EARTHDATA_USERNAME=...`, `EARTHDATA_PASSWORD=...`

### Step 10: Create `.dockerignore`

Исключить: `.git/`, `.venv/`, `__pycache__/`, `.idea/`, `.claude/`, `mod/`, `modis_data/`, `output/`, `parser.py`, `compare.py`, `setup_earthdata.py`, `test_search.py`, `catchments.geojson`, `main.js`, `docs/`, `Dockerfile`, `docker-compose.yml`, `.env`, `.github/`

### Step 11: Update `.gitignore`

```gitignore
__pycache__/
.venv/
.idea/
.claude/
modis_data/
output/
mod/
catchments.geojson
main.js
*.txt
!requirements.txt
.dodsrc
nul
.env
docker-compose.override.yml
```

`data/` НЕ в gitignore — tracked в git.

### Step 12: Create `.github/workflows/docker-publish.yml`

Trigger: push to `main` + workflow_dispatch.
Steps: checkout → Docker Buildx → login Docker Hub → build+push.
Tags: `latest`, git SHA, date (YYYYMMDD).
Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

### Step 13: Git cleanup

Удалить из отслеживания (не удалять файлы): `parser.py`, `compare.py`, `setup_earthdata.py`, `test_search.py`, `search_result*.txt`, `nul`, `.dodsrc`

## API Payload Format

```json
{
  "date": "2026-02-06",
  "catchments": [
    {
      "name": "Chirchik",
      "sca_pct": 99.49,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 83.49},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 96.63}
      ]
    }
  ]
}
```

## Risks

| Risk | Mitigation |
|------|-----------|
| netCDF4 не читает HDF4 в Linux | Протестировать в Docker рано; fallback: `apt-get install libhdf4-dev` |
| earthaccess env login не работает | earthaccess 0.12+ поддерживает `strategy="environment"` |
| API недоступен | 3 retry с backoff; HDF файлы сохраняются для повтора |
| Контейнер убит во время работы | `stop_grace_period: 5m` |

## Verification

1. `python run.py --once` — запуск pipeline один раз локально
2. `python run.py 2026-02-05` — для конкретной даты
3. `docker build -t modsnow-pipeline .` — сборка образа
4. `docker-compose up` — запуск с .env файлом
5. Проверить что HDF файлы удаляются после успешной отправки
6. Проверить формат JSON (нет лишних полей)
7. Push в main → GitHub Actions → образ в Docker Hub
