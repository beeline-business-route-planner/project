from src.core.db.models.base import Base
from src.core.db.models.baseline_result import BaselineResult
from src.core.db.models.data_upload import DataUpload
from src.core.db.models.engineer import Engineer
from src.core.db.models.engineer_skill import EngineerSkill
from src.core.db.models.plan import Plan
from src.core.db.models.plan_engineer_state import PlanEngineerState
from src.core.db.models.plan_stop import PlanStop
from src.core.db.models.plan_unassigned_request import PlanUnassignedRequest
from src.core.db.models.replanning_event import ReplanningEvent
from src.core.db.models.request import Request
from src.core.db.models.uploaded_file import UploadedFile

# Alembic's env.py imports Base from this package (not from .base directly).
# Every new model module must be imported here so it registers on Base.metadata
# and alembic autogenerate picks it up, e.g.:
# from src.core.db.models.user import User

__all__ = [
    "Base",
    "BaselineResult",
    "DataUpload",
    "Engineer",
    "EngineerSkill",
    "Plan",
    "PlanEngineerState",
    "PlanStop",
    "PlanUnassignedRequest",
    "ReplanningEvent",
    "Request",
    "UploadedFile",
]
