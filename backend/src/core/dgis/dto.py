import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DgisPoint:
    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal
