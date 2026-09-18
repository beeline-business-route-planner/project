from fastapi import HTTPException


class Base(HTTPException):
    status_code: int
    detail: str
    headers: dict[str, str] | None = None

    def __init__(self) -> None:
        super().__init__(status_code=self.status_code, detail=self.detail, headers=self.headers)
