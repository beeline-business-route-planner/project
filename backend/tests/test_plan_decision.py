import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from src.api.exc.plans import PlanStopAlreadyStartedError
from src.api.plans.service import PlanService
from src.config import cfg
from src.core.db.enums import ApprovalStatus, PlanKind
from src.core.utils.initial_approval import InitialApprovalPolicy


class InitialApprovalPolicyTest(unittest.TestCase):
    def test_deadline_is_inclusive_and_uses_config(self) -> None:
        created_at = datetime(2026, 9, 24, 10)
        deadline = created_at + timedelta(minutes=cfg.planning.approval_ttl_minutes)

        self.assertEqual(InitialApprovalPolicy.deadline(created_at), deadline)
        self.assertTrue(InitialApprovalPolicy.is_valid(created_at, deadline))
        self.assertFalse(
            InitialApprovalPolicy.is_valid(created_at, deadline + timedelta(microseconds=1))
        )

    def test_moscow_cutoff_is_compared_to_utc_database_timestamps(self) -> None:
        self.assertEqual(
            PlanService._cutoff_in_utc(datetime(2026, 9, 24, 10)),
            datetime(2026, 9, 24, 7),
        )


class ApprovalAvailabilityTest(unittest.TestCase):
    def test_initial_plan_can_be_approved_only_on_planning_day_before_deadline(self) -> None:
        created_at = datetime(2026, 9, 26, 21, 5)
        plan = SimpleNamespace(
            approval_status=ApprovalStatus.PENDING,
            kind=PlanKind.INITIAL,
            planning_date=datetime(2026, 9, 27).date(),
            created_at=created_at,
        )
        # 26 сентября 23:10 в Москве: для плана на 27-е ещё рано.
        self.assertFalse(PlanService._can_approve(plan, datetime(2026, 9, 26, 20, 10, tzinfo=UTC)))
        # В рабочий день можно утвердить до истечения TTL.
        self.assertTrue(PlanService._can_approve(plan, datetime(2026, 9, 26, 21, 10, tzinfo=UTC)))
        expired = created_at + timedelta(minutes=cfg.planning.approval_ttl_minutes, seconds=1)
        self.assertFalse(PlanService._can_approve(plan, expired.replace(tzinfo=UTC)))
        plan.approval_status = ApprovalStatus.APPROVED
        self.assertFalse(PlanService._can_approve(plan, datetime(2026, 9, 26, 21, 10, tzinfo=UTC)))

    def test_replan_requires_planning_day(self) -> None:
        plan = SimpleNamespace(
            approval_status=ApprovalStatus.PENDING,
            kind=PlanKind.REPLAN,
            planning_date=datetime(2026, 9, 27).date(),
        )
        self.assertFalse(PlanService._can_approve(plan, datetime(2026, 9, 26, 20, tzinfo=UTC)))
        self.assertTrue(PlanService._can_approve(plan, datetime(2026, 9, 26, 21, tzinfo=UTC)))


class PastStopDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 24, 12)
        self.request_id = uuid.uuid7()
        self.engineer_id = uuid.uuid7()

    def _stop(self, **overrides: object) -> SimpleNamespace:
        values = {
            "request_id": self.request_id,
            "engineer_id": self.engineer_id,
            "sequence_number": 1,
            "planned_arrival": self.now - timedelta(hours=1, minutes=10),
            "planned_start": self.now - timedelta(hours=1),
            "planned_finish": self.now - timedelta(minutes=10),
            "travel_minutes": 10,
            "distance_km": Decimal("2.00"),
            "is_locked": True,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_exact_locked_history_is_allowed(self) -> None:
        PlanService._validate_past_stops([self._stop()], [self._stop()], self.now)

    def test_removed_past_stop_is_rejected(self) -> None:
        with self.assertRaises(PlanStopAlreadyStartedError):
            PlanService._validate_past_stops([], [self._stop()], self.now)

    def test_changed_past_stop_is_rejected(self) -> None:
        with self.assertRaises(PlanStopAlreadyStartedError):
            PlanService._validate_past_stops(
                [self._stop(travel_minutes=12)], [self._stop()], self.now
            )

    def test_rescheduled_past_stop_is_rejected(self) -> None:
        with self.assertRaises(PlanStopAlreadyStartedError):
            PlanService._validate_past_stops(
                [self._stop(planned_start=self.now + timedelta(minutes=10))],
                [self._stop()],
                self.now,
            )

    def test_unlocked_past_stop_is_rejected(self) -> None:
        with self.assertRaises(PlanStopAlreadyStartedError):
            PlanService._validate_past_stops(
                [self._stop(is_locked=False)], [self._stop()], self.now
            )
