from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Coordinates:
    latitude: Decimal
    longitude: Decimal
