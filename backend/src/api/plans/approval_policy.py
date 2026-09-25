from datetime import datetime, timedelta

from src.config import cfg
from src.core.db.models import Plan


class InitialApprovalPolicy:
    """Временная проверка актуальности initial до согласования доменного правила."""

    @staticmethod
    def deadline(plan: Plan) -> datetime:
        return plan.created_at + timedelta(minutes=cfg.planning.approval_ttl_minutes)

    @staticmethod
    def is_valid(plan: Plan, now: datetime) -> bool:
        return now <= InitialApprovalPolicy.deadline(plan)
