from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from src.config import cfg
from src.core.geocoding import GeocodingClient, GeocodingService


class GeocodingProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_http_session(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url=cfg.geocoding.base_url,
            headers={"User-Agent": cfg.geocoding.user_agent},
            timeout=cfg.geocoding.timeout_seconds,
        ) as session:
            yield session

    @provide(scope=Scope.APP)
    def get_geocoding_client(self, session: httpx.AsyncClient) -> GeocodingClient:
        return GeocodingClient(session)

    @provide(scope=Scope.APP)
    def get_geocoding_service(self, client: GeocodingClient) -> GeocodingService:
        return GeocodingService(client)
