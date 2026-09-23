import uuid
from dataclasses import dataclass
from datetime import date, datetime

from src.core.db.enums import Region, ReplanningEventType


@dataclass(frozen=True)
class ReplanningEventCreateDTO:
    region: Region
    planning_date: date
    event_type: ReplanningEventType
    request_id: uuid.UUID | None
    engineer_id: uuid.UUID | None
    occurred_at: datetime
