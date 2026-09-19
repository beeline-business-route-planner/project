from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from beeline_backend.domain.errors import DomainError
from beeline_backend.domain.model import (
    RequestStatus,
    VisitWindow,
    calculate_visit,
    validate_status_transition,
)

MOSCOW = ZoneInfo("Europe/Moscow")


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=MOSCOW)


def test_visit_waits_and_must_finish_inside_window_and_shift() -> None:
    visit = calculate_visit(dt(8), 30 * 60, VisitWindow(dt(10), dt(12)), 70, dt(18))
    assert visit.arrival == dt(8, 30)
    assert visit.start == dt(10)
    assert visit.finish == dt(11, 10)

    with pytest.raises(DomainError, match="client window") as exc_info:
        calculate_visit(dt(10), 30 * 60, VisitWindow(dt(10), dt(11)), 70, dt(18))
    assert exc_info.value.code == "outside_client_window"


def test_sent_is_replannable_but_execution_statuses_are_not_reversed() -> None:
    validate_status_transition(RequestStatus.NOT_SENT, RequestStatus.SENT)
    validate_status_transition(RequestStatus.SENT, RequestStatus.EN_ROUTE)
    with pytest.raises(DomainError) as exc_info:
        validate_status_transition(RequestStatus.EN_ROUTE, RequestStatus.SENT)
    assert exc_info.value.code == "invalid_status_transition"

