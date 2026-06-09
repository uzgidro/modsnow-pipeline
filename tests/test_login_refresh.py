"""
Тесты авто-перевыпуска токена в download_modis.login().

Сеть НЕ используется: earthaccess полностью замокан. Проверяем логику
fallback'а — что при провале первой авторизации программа сама
перевыпускает токен из логина/пароля.

Запуск:  python -m pytest test_login_refresh.py -v
"""

import types

import pytest

import download_modis


class FakeAuth:
    """Мок earthaccess.Auth со взводимым флагом authenticated."""

    def __init__(self, authenticated=False):
        self.authenticated = authenticated


@pytest.fixture
def fake_earthaccess(monkeypatch):
    """Фабрика фейкового модуля earthaccess.

    Возвращает функцию make(login_results): login_results — список значений
    authenticated, которые earthaccess.login() отдаёт по очереди (имитируем,
    например: 1-й логин протух → False, 2-й перевыпуск → True).

    Считает вызовы login() в fake._calls["login"].
    """

    def make(login_results):
        fake = types.SimpleNamespace()
        fake.__auth__ = FakeAuth(authenticated=False)
        fake._calls = {"login": []}

        def fake_login(strategy=None, persist=False):
            fake._calls["login"].append((strategy, persist))
            authed = login_results.pop(0)
            fake.__auth__.authenticated = authed
            return FakeAuth(authenticated=authed)

        fake.login = fake_login
        monkeypatch.setattr(download_modis, "earthaccess", fake)
        return fake

    return make


@pytest.fixture
def creds(monkeypatch):
    """Выставить валидные env-креды Earthdata."""
    monkeypatch.setenv("EARTHDATA_USERNAME", "u")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "p")


def test_reissue_on_expired_token(fake_earthaccess, creds):
    """Протухший токен → fallback перевыпускает, login() возвращает успех."""
    fake = fake_earthaccess([False, True])

    auth = download_modis.login()

    assert auth.authenticated is True
    # Первичный логин + перевыпуск = 2 вызова
    assert len(fake._calls["login"]) == 2


def test_happy_path_no_reissue(fake_earthaccess, creds):
    """Валидный токен с первого раза → перевыпуск не нужен."""
    fake = fake_earthaccess([True])

    auth = download_modis.login()

    assert auth.authenticated is True
    assert len(fake._calls["login"]) == 1


def test_no_credentials_raises(fake_earthaccess, monkeypatch):
    """Нет кредов и логин провалился → RuntimeError, без перевыпуска."""
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    fake = fake_earthaccess([False])

    with pytest.raises(RuntimeError, match="Earthdata"):
        download_modis.login()

    # Перевыпуск не должен запускаться без кредов — ровно один вызов login
    assert len(fake._calls["login"]) == 1


def test_reissue_still_failing_raises(fake_earthaccess, creds):
    """Креды есть, но и перевыпуск не помог → RuntimeError."""
    fake = fake_earthaccess([False, False])

    with pytest.raises(RuntimeError, match="Earthdata"):
        download_modis.login()

    assert len(fake._calls["login"]) == 2
