import uuid

from pydantic import BaseModel

from src.core.db.enums import Region


class PlanningImportResponse(BaseModel):
    upload_id: uuid.UUID
    region: Region
    requests_count: int
    engineers_count: int


class InitialPlanningResponse(BaseModel):
    status: str
    imports: list[PlanningImportResponse]
