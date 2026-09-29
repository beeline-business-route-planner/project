"""Event input validation stays in the unit layer."""

import unittest
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from src.api.planning.schemas import EventPlanningRequest
from src.core.db.enums import Region, ReplanningEventType


class EventRequestValidationTest(unittest.TestCase):
    def test_one_target_and_server_owned_time(self) -> None:
        with self.assertRaises(ValidationError):
            EventPlanningRequest.model_validate(
                {
                    "region": Region.VOSTOK,
                    "event_type": ReplanningEventType.REQUEST_CANCELLED,
                    "request_id": str(uuid.uuid7()),
                    "engineer_id": str(uuid.uuid7()),
                }
            )
        with self.assertRaises(ValidationError):
            EventPlanningRequest.model_validate(
                {
                    "region": Region.VOSTOK,
                    "event_type": ReplanningEventType.REQUEST_CANCELLED,
                    "request_id": str(uuid.uuid7()),
                    "occurred_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
                }
            )
