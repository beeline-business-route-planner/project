from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExportDownload:
    url: str
    expires_at: datetime
    filename: str
    content_type: str
    size_bytes: int
