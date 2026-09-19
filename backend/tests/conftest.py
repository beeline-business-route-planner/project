from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from beeline_backend.config import Settings
from beeline_backend.presentation.api import create_app


@pytest.fixture
def synthetic_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Лист 1 - Восток Синтетические д"
    sheet.append(["Восток Синтетические данные"])
    sheet.append(
        [
            "Заявка",
            "Тип заявки BK",
            "Тип заявки HD",
            "Начало",
            "Окончание",
            "Район",
            "Адрес",
            "Подключение",
            "Гигабитное подключение",
        ]
    )
    sheet.append(
        [
            1001,
            "Локальная заявка",
            "Нет линка",
            "17.08.2026 08:00",
            "17.08.2026 23:00",
            "Кузьминки",
            "Москва, ул. Тестовая, д. 1",
            None,
            "Нет",
        ]
    )
    sheet.append(
        [
            1002,
            "Локальная заявка",
            "Работа с кабелем",
            "17.08.2026 08:00",
            "17.08.2026 23:00",
            "Кузьминки",
            "Москва, ул. Тестовая, д. 1",
            None,
            "Нет",
        ]
    )
    sheet.append([None])
    sheet.append(["Адрес Офиса", "г. Москва, ул. Юных Ленинцев, д. 83с4"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        geocoder_mode="demo",
        routing_provider="demo",
        cors_origins=["http://testserver"],
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client

