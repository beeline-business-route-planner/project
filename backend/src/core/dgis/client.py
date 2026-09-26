import httpx


class DgisClient:
    """Держит выделенную HTTP-сессию 2ГИС."""

    def __init__(self, session: httpx.AsyncClient) -> None:
        self._session = session

    def get(self) -> httpx.AsyncClient:
        return self._session
