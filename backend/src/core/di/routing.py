from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from src.config import cfg
from src.core.routing import RoutingClient, RoutingService


class RoutingProvider(Provider):
    """Регистрирует HTTP-сессию/клиент/сервис маршрутизации.

    HTTP-сессия создаётся внутри этого же провайдера (не как отдельный
    `provide`-метод, возвращающий `httpx.AsyncClient`) — иначе два разных
    провайдера (`GeocodingProvider` и этот) регистрировали бы один и тот же
    тип `httpx.AsyncClient` в одном контейнере, что dishka не допускает.
    """

    @provide(scope=Scope.APP)
    async def get_routing_client(self) -> AsyncIterator[RoutingClient]:
        async with httpx.AsyncClient(
            base_url=cfg.routing.base_url,
            timeout=cfg.routing.timeout_seconds,
        ) as session:
            yield RoutingClient(session)

    @provide(scope=Scope.APP)
    def get_routing_service(self, client: RoutingClient) -> RoutingService:
        return RoutingService(client)
