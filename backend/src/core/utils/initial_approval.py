from datetime import datetime, timedelta

from src.config import cfg


class InitialApprovalPolicy:
    """Временный TTL initial; created_at и now — UTC без TZ."""

    @staticmethod
    def deadline(created_at: datetime) -> datetime:
        return created_at + timedelta(minutes=cfg.planning.approval_ttl_minutes)

    @staticmethod
    def is_valid(created_at: datetime, now: datetime) -> bool:
        return now <= InitialApprovalPolicy.deadline(created_at)
