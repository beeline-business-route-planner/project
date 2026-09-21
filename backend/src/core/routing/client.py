import httpx


class RoutingClient:
    """Тонкая обёртка над HTTP-сессией провайдера маршрутизации."""

    def __init__(self, session: httpx.AsyncClient) -> None:
        self._session = session

    def get(self) -> httpx.AsyncClient:
        return self._session
