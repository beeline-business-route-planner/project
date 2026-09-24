from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from src.config import cfg
from src.core.dgis import DgisClient, DgisMatrixService


class DgisProvider(Provider):
    """Регистрирует изолированный клиент 2ГИС Distance Matrix API."""

    @provide(scope=Scope.APP)
    async def get_dgis_client(self) -> AsyncIterator[DgisClient]:
        async with httpx.AsyncClient(
            base_url=cfg.dgis.base_url,
            timeout=cfg.dgis.timeout_seconds,
        ) as session:
            yield DgisClient(session)

    @provide(scope=Scope.APP)
    def get_dgis_matrix_service(self, client: DgisClient) -> DgisMatrixService:
        return DgisMatrixService(client)
