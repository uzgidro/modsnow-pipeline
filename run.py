"""
Оркестратор MODIS SCA pipeline.

Режимы запуска:
  python run.py --once         → один раз (today) и выйти
  python run.py 2026-02-10     → для конкретной даты и выйти
  python run.py                → HTTP-сервер + ежедневно по расписанию
"""

import asyncio
import logging
import os
import secrets
import shutil
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from api_client import send_results
from download_modis import download_for_date, login
from process_modis import process_day

logger = logging.getLogger("modsnow")

# Глобальные объекты
_config: dict = {}
_scheduler: BackgroundScheduler | None = None
_pipeline_lock = threading.Lock()


def load_config() -> dict:
    """Загрузить конфигурацию из YAML файла."""
    config_path = os.environ.get("CONFIG_PATH", "config/config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


class _HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "GET /health" not in msg


def setup_logging(config: dict):
    """Настроить логирование."""
    level = config.get("logging", {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("uvicorn.access").addFilter(_HealthFilter())


def cleanup_hdf(hdf_dir: Path):
    """Удалить HDF файлы и директорию после успешной отправки."""
    if hdf_dir.exists():
        shutil.rmtree(hdf_dir)
        logger.info("Удалено: %s", hdf_dir)


def run_pipeline(config: dict, date_str: str = None):
    """
    Основной pipeline: скачивание → обработка → отправка → очистка.

    Args:
        date_str: Дата запроса (YYYY-MM-DD). resource_date вычисляется как
                  date_str - days_behind. Если None — берётся сегодня UTC.
    """
    modis_cfg = config.get("modis", {})
    paths_cfg = config.get("paths", {})
    api_cfg = config.get("api", {})
    days_behind = modis_cfg.get("days_behind", 3)

    # Определить дату запроса и дату ресурса
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    request_date = datetime.strptime(date_str, "%Y-%m-%d")
    resource_date = request_date - timedelta(days=days_behind)
    resource_date_str = resource_date.strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("Pipeline: дата запроса %s, дата ресурса %s", date_str, resource_date_str)
    logger.info("=" * 60)

    # 1. Скачать (по дате ресурса)
    try:
        login()
        hdf_dir = download_for_date(
            date_str=resource_date_str,
            download_dir=paths_cfg.get("download_dir", "modis_data"),
            bbox=tuple(modis_cfg.get("bbox", [55, 33, 85, 50])),
            product=modis_cfg.get("product", "MOD10A1F"),
            version=modis_cfg.get("version", "61"),
        )
    except Exception as e:
        logger.error("Ошибка скачивания: %s", e)
        raise

    # 2. Обработать
    try:
        results = process_day(
            hdf_dir=str(hdf_dir),
            data_dir=paths_cfg.get("data_dir", "data"),
        )
    except Exception as e:
        logger.error("Ошибка обработки: %s", e)
        raise

    # 3. Отправить
    payload = {
        "date": date_str,
        "resource_date": resource_date_str,
        "catchments": results,
    }

    api_key = os.environ.get("API_KEY") or api_cfg.get("api_key")
    send_cfg = {**api_cfg}
    if api_key:
        send_cfg["api_key"] = api_key

    success = send_results(payload, send_cfg)

    # 4. Очистка
    if success:
        cleanup_hdf(hdf_dir)
    else:
        logger.warning("Данные сохранены в %s для повторной отправки", hdf_dir)

    return {"date": date_str, "resource_date": resource_date_str, "success": success}


def _scheduled_run():
    """Обёртка для запуска по расписанию (без пробрасывания исключений)."""
    try:
        run_pipeline(_config)
    except Exception as e:
        logger.error("Ошибка pipeline по расписанию: %s", e)


# ── FastAPI ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запуск/остановка scheduler вместе с FastAPI."""
    global _scheduler
    schedule_time = _config.get("schedule", {}).get("time", "06:00")
    hour, minute = map(int, schedule_time.split(":"))

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scheduled_run,
        CronTrigger(hour=hour, minute=minute),
        misfire_grace_time=3600,
        id="daily_pipeline",
    )
    _scheduler.start()
    logger.info("Расписание: ежедневно в %s UTC", schedule_time)

    yield

    _scheduler.shutdown(wait=False)
    logger.info("Scheduler остановлен")


app = FastAPI(title="MODSNOW Pipeline", lifespan=lifespan)

_bearer_scheme = HTTPBearer()


def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> str:
    """Проверка Bearer-токена из заголовка Authorization."""
    expected = os.environ.get("API_KEY") or _config.get("api", {}).get("api_key", "")
    if not expected or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=403, detail="Неверный API-ключ")
    return credentials.credentials


class TriggerRequest(BaseModel):
    date: str  # YYYY-MM-DD


class TriggerResponse(BaseModel):
    date: str
    resource_date: str
    success: bool


@app.post("/api/trigger", response_model=TriggerResponse)
async def trigger_pipeline(body: TriggerRequest, _key: str = Depends(verify_api_key)):
    """Ручной запуск pipeline для указанной даты."""
    # Валидация формата даты
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, ожидается YYYY-MM-DD")

    if not _pipeline_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Pipeline уже выполняется")

    try:
        result = await asyncio.to_thread(run_pipeline, _config, body.date)
    except Exception:
        logger.exception("Ошибка pipeline (trigger)")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка pipeline")
    finally:
        _pipeline_lock.release()

    return result


@app.get("/health")
def health():
    return {"status": "ok"}


# ── CLI ──────────────────────────────────────────────────────


def main():
    global _config
    _config = load_config()
    setup_logging(_config)

    args = sys.argv[1:]

    # Режим: однократный запуск
    if "--once" in args:
        logger.info("Режим: однократный запуск")
        try:
            run_pipeline(_config)
        except Exception:
            logger.exception("Pipeline завершился с ошибкой")
            sys.exit(1)
        return

    # Режим: конкретная дата
    if args and not args[0].startswith("-"):
        date_str = args[0]
        logger.info("Режим: конкретная дата %s", date_str)
        try:
            run_pipeline(_config, date_str=date_str)
        except Exception:
            logger.exception("Pipeline завершился с ошибкой")
            sys.exit(1)
        return

    # Режим: HTTP-сервер + расписание
    logger.info("Режим: HTTP-сервер + расписание")

    # Запуск pipeline при старте
    logger.info("Запуск pipeline при старте...")
    try:
        run_pipeline(_config)
    except Exception:
        logger.exception("Pipeline при старте завершился с ошибкой (продолжаем)")

    server_cfg = _config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 8000)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
