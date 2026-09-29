from collections.abc import Sequence

from src.config import cfg
from src.core.dgis import (
    DgisMatrix,
    DgisMatrixService,
    DgisPoint,
    DgisUnavailableError,
    InvalidDgisResponseError,
)
from src.core.routing import (
    InvalidRoutingResponseError,
    RoutingMatrix,
    RoutingPoint,
    RoutingService,
    RoutingUnavailableError,
)
from src.core.travel_matrix.dto import MatrixPoint, MatrixRequest
from src.core.travel_matrix.exc import (
    InvalidTravelMatrixResponseError,
    TravelMatrixUnavailableError,
)


class TravelMatrixService:
    """Отдаёт матрицы времени и расстояния от провайдера из `cfg.travel_matrix.provider`.

    `dgis` — матрица на каждый запрос с учётом пробок в опорное время слоя.
    `osrm` — без пробок: на тип транспорта одна матрица «все со всеми», ею отвечают
    на все запросы этого транспорта.
    """

    def __init__(self, dgis: DgisMatrixService, osrm: RoutingService) -> None:
        self._dgis = dgis
        self._osrm = osrm

    async def build(
        self, points: Sequence[MatrixPoint], requests: Sequence[MatrixRequest]
    ) -> list[DgisMatrix | RoutingMatrix]:
        """Возвращает матрицу на каждый запрос в том же порядке.

        Raises:
            TravelMatrixUnavailableError: если провайдер недоступен или исчерпан его лимит.
            InvalidTravelMatrixResponseError: если провайдер ответил не по формату.
        """

        try:
            if cfg.travel_matrix.provider == "dgis":
                return await self._build_dgis(points, requests)
            return await self._build_osrm(points, requests)
        except (DgisUnavailableError, RoutingUnavailableError) as exc:
            raise TravelMatrixUnavailableError(str(exc)) from exc
        except (InvalidDgisResponseError, InvalidRoutingResponseError) as exc:
            raise InvalidTravelMatrixResponseError(str(exc)) from exc

    async def _build_dgis(
        self, points: Sequence[MatrixPoint], requests: Sequence[MatrixRequest]
    ) -> list[DgisMatrix | RoutingMatrix]:
        dgis_points = [
            DgisPoint(id=point.id, latitude=point.latitude, longitude=point.longitude)
            for point in points
        ]
        return [
            await self._dgis.build_matrix(
                dgis_points,
                vehicle_type=request.vehicle_type,
                departure_at=request.departure_at,
                source_ids=request.source_ids,
                target_ids=request.target_ids,
            )
            for request in requests
        ]

    async def _build_osrm(
        self, points: Sequence[MatrixPoint], requests: Sequence[MatrixRequest]
    ) -> list[DgisMatrix | RoutingMatrix]:
        if not requests:
            return []
        matrices = await self._osrm.build_matrices(
            [
                RoutingPoint(id=point.id, latitude=point.latitude, longitude=point.longitude)
                for point in points
            ],
            {request.vehicle_type for request in requests},
        )
        return [matrices[request.vehicle_type] for request in requests]
