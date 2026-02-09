"""REST API клиент для отправки результатов SCA."""

import logging
import time

import requests

logger = logging.getLogger(__name__)


def send_results(payload: dict, api_config: dict) -> bool:
    """
    Отправить результаты SCA на REST API.

    Args:
        payload: JSON данные для отправки.
        api_config: Конфигурация API (url, api_key, timeout, retries).

    Returns:
        True если отправка успешна, False если все попытки исчерпаны.
    """
    url = api_config["url"]
    timeout = api_config.get("timeout", 30)
    retries = api_config.get("retries", 3)
    api_key = api_config.get("api_key")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for attempt in range(1, retries + 1):
        try:
            logger.info("Отправка на %s (попытка %d/%d)...", url, attempt, retries)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            logger.info("Успешно отправлено: %d %s", resp.status_code, resp.reason)
            return True
        except requests.RequestException as e:
            logger.warning("Попытка %d/%d не удалась: %s", attempt, retries, e)
            if attempt < retries:
                delay = 2 ** attempt
                logger.info("Повтор через %dс...", delay)
                time.sleep(delay)

    logger.error("Все %d попыток отправки исчерпаны", retries)
    return False
