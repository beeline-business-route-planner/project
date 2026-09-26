import httpx


class GeocodingClient:
    """Тонкая обёртка над HTTP-сессией геокодера."""

    def __init__(self, session: httpx.AsyncClient) -> None:
        self._session = session

    def get(self) -> httpx.AsyncClient:
        return self._session
