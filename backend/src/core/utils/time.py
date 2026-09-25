from datetime import UTC, datetime
from typing import overload


@overload
def as_utc(value: datetime) -> datetime: ...


@overload
def as_utc(value: None) -> None: ...


def as_utc(value: datetime | None) -> datetime | None:
    """Добавляет UTC к системному timestamp из PostgreSQL без смены времени."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
