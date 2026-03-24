"""Тесты для логики отката даты при отсутствии данных MODIS."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from run import run_pipeline


@pytest.fixture
def base_config():
    return {
        "modis": {
            "days_behind": 3,
            "max_fallback_days": 2,
            "bbox": [55, 33, 85, 50],
            "product": "MOD10A1F",
            "version": "61",
        },
        "paths": {"data_dir": "data", "download_dir": "modis_data"},
        "api": {"url": "http://test", "timeout": 5, "retries": 1},
    }


@patch("run.send_results", return_value=True)
@patch("run.cleanup_hdf")
@patch("run.process_day", return_value=[{"id": 1, "sca": 50.0}])
@patch("run.download_for_date")
@patch("run.login")
def test_no_fallback_when_data_available(
    mock_login, mock_download, mock_process, mock_cleanup, mock_send, base_config
):
    """Данные есть за resource_date — откат не нужен."""
    mock_download.return_value = Path("modis_data/2026-03-21")

    result = run_pipeline(base_config, date_str="2026-03-24")

    assert result["resource_date"] == "2026-03-21"
    assert result["success"] is True
    mock_download.assert_called_once()
    assert mock_download.call_args.kwargs["date_str"] == "2026-03-21"


@patch("run.send_results", return_value=True)
@patch("run.cleanup_hdf")
@patch("run.process_day", return_value=[{"id": 1, "sca": 50.0}])
@patch("run.download_for_date")
@patch("run.login")
def test_fallback_one_day(
    mock_login, mock_download, mock_process, mock_cleanup, mock_send, base_config
):
    """Данных нет за resource_date, но есть за resource_date-1."""
    mock_download.side_effect = [None, Path("modis_data/2026-03-20")]

    result = run_pipeline(base_config, date_str="2026-03-24")

    assert result["resource_date"] == "2026-03-20"
    assert result["success"] is True
    assert mock_download.call_count == 2


@patch("run.send_results", return_value=True)
@patch("run.cleanup_hdf")
@patch("run.process_day", return_value=[{"id": 1, "sca": 50.0}])
@patch("run.download_for_date")
@patch("run.login")
def test_fallback_two_days(
    mock_login, mock_download, mock_process, mock_cleanup, mock_send, base_config
):
    """Данных нет 2 дня подряд, есть на 3-й попытке (fallback=2)."""
    mock_download.side_effect = [None, None, Path("modis_data/2026-03-19")]

    result = run_pipeline(base_config, date_str="2026-03-24")

    assert result["resource_date"] == "2026-03-19"
    assert mock_download.call_count == 3


@patch("run.download_for_date", return_value=None)
@patch("run.login")
def test_fallback_exhausted_raises(mock_login, mock_download, base_config):
    """Все попытки исчерпаны — RuntimeError."""
    with pytest.raises(RuntimeError, match=r"Нет данных за 3 дн\. \(2026-03-21 \.\. 2026-03-19\)"):
        run_pipeline(base_config, date_str="2026-03-24")

    # max_fallback_days=2 → 3 попытки (0, 1, 2)
    assert mock_download.call_count == 3


@patch("run.send_results", return_value=True)
@patch("run.cleanup_hdf")
@patch("run.process_day", return_value=[])
@patch("run.download_for_date")
@patch("run.login")
def test_fallback_zero_no_retry(
    mock_login, mock_download, mock_process, mock_cleanup, mock_send, base_config
):
    """max_fallback_days=0 — одна попытка, без отката."""
    base_config["modis"]["max_fallback_days"] = 0
    mock_download.return_value = Path("modis_data/2026-03-21")

    result = run_pipeline(base_config, date_str="2026-03-24")

    mock_download.assert_called_once()


@patch("run.download_for_date", return_value=None)
@patch("run.login")
def test_fallback_zero_raises_immediately(mock_login, mock_download, base_config):
    """max_fallback_days=0 и данных нет — сразу RuntimeError."""
    base_config["modis"]["max_fallback_days"] = 0

    with pytest.raises(RuntimeError, match=r"Нет данных за 2026-03-21"):
        run_pipeline(base_config, date_str="2026-03-24")

    assert mock_download.call_count == 1


@patch("run.download_for_date")
@patch("run.login")
def test_download_error_propagates(mock_login, mock_download, base_config):
    """Ошибка скачивания (не None) пробрасывается, а не пробует следующий день."""
    mock_download.side_effect = RuntimeError("Скачивание не удалось")

    with pytest.raises(RuntimeError, match="Скачивание не удалось"):
        run_pipeline(base_config, date_str="2026-03-24")

    # Только 1 вызов — ошибка не приводит к откату
    assert mock_download.call_count == 1
