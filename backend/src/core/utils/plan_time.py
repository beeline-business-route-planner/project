from datetime import datetime, timedelta


def latest_departure_at(start: datetime, travel_minutes: int) -> datetime:
    return start - timedelta(minutes=travel_minutes)
