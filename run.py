"""
Оркестратор MODIS SCA pipeline.

Режимы запуска:
  python run.py --once         → один раз (today - days_behind) и выйти
  python run.py 2026-02-06     → для конкретной даты и выйти
  python run.py                → startup + ежедневно по расписанию
"""

import logging
import os
import shutil
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from api_client import send_results
from download_modis import download_for_date, login
from process_modis import process_day

logger = logging.getLogger("modsnow")

scheduler: BlockingScheduler | None = None


def load_config() -> dict:
    """Загрузить конфигурацию из YAML файла."""
    config_path = os.environ.get("CONFIG_PATH", "config/config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    """Настроить логирование."""
    level = config.get("logging", {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cleanup_hdf(hdf_dir: Path):
    """Удалить HDF файлы и директорию после успешной отправки."""
    if hdf_dir.exists():
        shutil.rmtree(hdf_dir)
        logger.info("Удалено: %s", hdf_dir)


def run_pipeline(config: dict, date_str: str = None):
    """
    Основной pipeline: скачивание → обработка → отправка → очистка.
    """
    modis_cfg = config.get("modis", {})
    paths_cfg = config.get("paths", {})
    api_cfg = config.get("api", {})

    # Определить дату
    if date_str is None:
        days_behind = modis_cfg.get("days_behind", 3)
        dt = datetime.now(timezone.utc) - timedelta(days=days_behind)
        date_str = dt.strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("Pipeline для %s", date_str)
    logger.info("=" * 60)

    # 1. Скачать
    try:
        login()
        hdf_dir = download_for_date(
            date_str=date_str,
            download_dir=paths_cfg.get("download_dir", "modis_data"),
            bbox=tuple(modis_cfg.get("bbox", [55, 33, 85, 50])),
            product=modis_cfg.get("product", "MOD10A1F"),
            version=modis_cfg.get("version", "61"),
        )
    except Exception as e:
        logger.error("Ошибка скачивания: %s", e)
        return

    # 2. Обработать
    try:
        results = process_day(
            hdf_dir=str(hdf_dir),
            data_dir=paths_cfg.get("data_dir", "data"),
        )
    except Exception as e:
        logger.error("Ошибка обработки: %s", e)
        return

    # 3. Отправить
    payload = {
        "date": date_str,
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


def graceful_shutdown(signum, frame):
    """Обработчик сигналов для graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info("Получен сигнал %s, завершение...", sig_name)
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    sys.exit(0)


def main():
    config = load_config()
    setup_logging(config)

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # CLI аргументы
    args = sys.argv[1:]

    if "--once" in args:
        logger.info("Режим: однократный запуск")
        run_pipeline(config)
        return

    if args and not args[0].startswith("-"):
        date_str = args[0]
        logger.info("Режим: конкретная дата %s", date_str)
        run_pipeline(config, date_str=date_str)
        return

    # Режим: расписание
    logger.info("Режим: расписание")
    schedule_time = config.get("schedule", {}).get("time", "06:00")
    hour, minute = map(int, schedule_time.split(":"))

    # Запуск при старте
    logger.info("Запуск pipeline при старте...")
    run_pipeline(config)

    # Настроить расписание
    global scheduler
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        CronTrigger(hour=hour, minute=minute),
        args=[config],
        misfire_grace_time=3600,
        id="daily_pipeline",
    )
    logger.info("Расписание: ежедневно в %s UTC", schedule_time)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Завершение работы")


if __name__ == "__main__":
    main()
