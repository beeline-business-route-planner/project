import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.db.enums import VehicleType


@dataclass(frozen=True)
class MatrixPoint:
    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal


@dataclass(frozen=True)
class MatrixRequest:
    """Какие переходы нужны алгоритму: транспорт, опорное время пробок, источники и цели."""

    vehicle_type: VehicleType
    departure_at: datetime
    source_ids: frozenset[uuid.UUID]
    target_ids: frozenset[uuid.UUID]
