import asyncio
import math
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal

import httpx

from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.routing.client import RoutingClient
from src.core.routing.dto import RoutingPoint
from src.core.routing.exc import InvalidRoutingResponseError, RoutingUnavailableError


class RoutingMatrix:
    """Полная матрица времени/расстояния «все со всеми»; `None` — маршрута нет."""

    def __init__(
        self,
        index_by_id: dict[uuid.UUID, int],
        travel_minutes: list[list[int | None]],
        distance_km: list[list[Decimal | None]],
    ) -> None:
        self._index_by_id = index_by_id
        self._travel_minutes = travel_minutes
        self._distance_km = distance_km

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int | None:
        return self._travel_minutes[self._index_by_id[from_id]][self._index_by_id[to_id]]

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal | None:
        return self._distance_km[self._index_by_id[from_id]][self._index_by_id[to_id]]


class RoutingService:
    """Строит матрицы OSRM `Table API` для всех типов транспорта инженеров.

    Пробки не учитываются, поэтому время не зависит от часа: на тип транспорта хватает
    одной матрицы «все со всеми». Машина, пешеход и велосипед — отдельные профили OSRM.
    Общественного транспорта в OSRM нет, он оценивается: лучшее из «дойти пешком» и
    «проехать дорожное расстояние со средней скоростью транспорта плюс ожидание».

    Публичные серверы ограничивают число точек одного запроса
    (`cfg.routing.max_table_coordinates`, для них ровно 100). Большая матрица
    собирается из нескольких запросов по парам блоков точек (см. `_iter_blocks`).
    """

    def __init__(self, client: RoutingClient) -> None:
        self._client = client

    async def build_matrices(
        self, points: Sequence[RoutingPoint], vehicle_types: set[VehicleType]
    ) -> dict[VehicleType, RoutingMatrix]:
        """Строит матрицу для каждого типа транспорта, запрашивая каждый профиль один раз.

        Raises:
            RoutingUnavailableError: если сервер OSRM недоступен.
            InvalidRoutingResponseError: если сервер отклонил запрос или ответил не по формату.
        """

        if len(points) < 2:
            raise ValueError("Матрица требует минимум 2 точки")
        needs_car = bool(vehicle_types & {VehicleType.CAR, VehicleType.PUBLIC_TRANSPORT})
        needs_foot = bool(vehicle_types & {VehicleType.PEDESTRIAN, VehicleType.PUBLIC_TRANSPORT})
        profiles = {
            vehicle: url
            for vehicle, url, needed in (
                (VehicleType.CAR, cfg.routing.car_table_url, needs_car),
                (VehicleType.PEDESTRIAN, cfg.routing.foot_table_url, needs_foot),
                (
                    VehicleType.BICYCLE,
                    cfg.routing.bike_table_url,
                    VehicleType.BICYCLE in vehicle_types,
                ),
            )
            if needed
        }
        tables = await asyncio.gather(*(self._table(points, url) for url in profiles.values()))
        by_profile = dict(zip(profiles, tables, strict=True))
        if VehicleType.PUBLIC_TRANSPORT in vehicle_types:
            by_profile[VehicleType.PUBLIC_TRANSPORT] = self._public_transport(
                by_profile[VehicleType.CAR], by_profile[VehicleType.PEDESTRIAN], len(points)
            )
        index_by_id = {point.id: index for index, point in enumerate(points)}
        return {
            vehicle: RoutingMatrix(index_by_id, *by_profile[vehicle]) for vehicle in vehicle_types
        }

    @staticmethod
    def _public_transport(
        car: tuple[list[list[int | None]], list[list[Decimal | None]]],
        foot: tuple[list[list[int | None]], list[list[Decimal | None]]],
        size: int,
    ) -> tuple[list[list[int | None]], list[list[Decimal | None]]]:
        speed_km_per_minute = Decimal(str(cfg.routing.public_transport_speed_kmh)) / 60
        travel_minutes: list[list[int | None]] = [[None] * size for _ in range(size)]
        distance_km: list[list[Decimal | None]] = [[None] * size for _ in range(size)]
        for i in range(size):
            for j in range(size):
                options: list[tuple[int, Decimal]] = []
                walk_minutes, walk_km = foot[0][i][j], foot[1][i][j]
                if walk_minutes is not None and walk_km is not None:
                    options.append((walk_minutes, walk_km))
                ride_km = car[1][i][j]
                if ride_km is not None:
                    ride_minutes = (
                        0
                        if i == j
                        else math.ceil(ride_km / speed_km_per_minute)
                        + cfg.routing.public_transport_wait_minutes
                    )
                    options.append((ride_minutes, ride_km))
                if options:
                    travel_minutes[i][j], distance_km[i][j] = min(options)
        return travel_minutes, distance_km

    async def _table(
        self, points: Sequence[RoutingPoint], url: str
    ) -> tuple[list[list[int | None]], list[list[Decimal | None]]]:
        index_by_id = {point.id: index for index, point in enumerate(points)}
        size = len(points)
        travel_minutes: list[list[int | None]] = [[None] * size for _ in range(size)]
        distance_km: list[list[Decimal | None]] = [[None] * size for _ in range(size)]
        for block in self._iter_blocks(points):
            block_travel, block_distance = await self._fetch_block(block, url)
            for local_i, point_i in enumerate(block):
                global_i = index_by_id[point_i.id]
                for local_j, point_j in enumerate(block):
                    global_j = index_by_id[point_j.id]
                    travel_minutes[global_i][global_j] = block_travel[local_i][local_j]
                    distance_km[global_i][global_j] = block_distance[local_i][local_j]
        return travel_minutes, distance_km

    def _iter_blocks(self, points: Sequence[RoutingPoint]) -> Iterator[list[RoutingPoint]]:
        """Разбивает точки на блоки, каждый из которых укладывается в лимит провайдера.

        Каждая упорядоченная пара точек должна попасть хотя бы в один блок,
        чтобы матрица получилась полной. Делим точки на непересекающиеся
        куски не больше половины лимита и берём каждую неупорядоченную пару
        кусков (включая пару "кусок сам с собой") — тогда объединение любых
        двух кусков не превышает лимит, а через все пары кусков проходят все
        пары точек: и внутри одного куска (диагональные блоки), и между
        разными (блок из объединения даёт сразу обе стороны, `driving`
        асимметричен, но обе строки/столбца уже есть в одном ответе).
        """
        limit = cfg.routing.max_table_coordinates
        if len(points) <= limit:
            yield list(points)
            return

        chunk_size = max(limit // 2, 1)
        chunks = [list(points[i : i + chunk_size]) for i in range(0, len(points), chunk_size)]
        for i, chunk_a in enumerate(chunks):
            for chunk_b in chunks[i:]:
                yield chunk_a if chunk_a is chunk_b else chunk_a + chunk_b

    async def _fetch_block(
        self, points: Sequence[RoutingPoint], url: str
    ) -> tuple[list[list[int | None]], list[list[Decimal | None]]]:
        coordinates = ";".join(f"{point.longitude},{point.latitude}" for point in points)
        try:
            response = await self._client.get().get(
                f"{url}/{coordinates}", params={"annotations": "duration,distance"}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise InvalidRoutingResponseError(
                f"OSRM отклонил запрос со статусом {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RoutingUnavailableError("Сервис маршрутизации недоступен") from exc
        except ValueError as exc:
            raise InvalidRoutingResponseError("OSRM вернул невалидный JSON") from exc

        if not isinstance(payload, dict) or payload.get("code") != "Ok":
            raise InvalidRoutingResponseError("OSRM вернул код ошибки")

        durations = payload.get("durations")
        distances = payload.get("distances")
        if not isinstance(durations, list) or not isinstance(distances, list):
            raise InvalidRoutingResponseError("Провайдер вернул некорректный формат матрицы")

        try:
            travel_minutes: list[list[int | None]] = [
                [
                    math.ceil((seconds / 60) * cfg.routing.travel_buffer_multiplier)
                    if seconds is not None
                    else None
                    for seconds in row
                ]
                for row in durations
            ]
            distance_km: list[list[Decimal | None]] = [
                [Decimal(str(meters / 1000)) if meters is not None else None for meters in row]
                for row in distances
            ]
        except (TypeError, ValueError) as exc:
            raise InvalidRoutingResponseError("Провайдер вернул некорректные значения") from exc

        return travel_minutes, distance_km
