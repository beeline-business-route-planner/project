from datetime import datetime

from pydantic import BaseModel


class DailyReportExportResponse(BaseModel):
    url: str
    expires_at: datetime
    filename: str
    content_type: str
    size_bytes: int
