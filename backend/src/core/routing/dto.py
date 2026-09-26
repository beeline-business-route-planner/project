import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RoutingPoint:
    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal
