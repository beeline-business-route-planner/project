import math
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal

import httpx

from src.config import cfg
from src.core.routing.client import RoutingClient
from src.core.routing.dto import RoutingPoint
from src.core.routing.exc import (
    InvalidRoutingResponseError,
    RoutingUnavailableError,
    UnreachablePointsError,
)


class RoutingMatrix:
    """Матрица времени/расстояния между точками — реализация `algorithm.TravelMatrix`.

    Хранит полный результат построения матрицы (одного или нескольких
    запросов `Table API`, см. `RoutingService.build_matrix`). Недостижимая
    пара (OSRM вернул `null`) не считается ошибкой всей матрицы заранее —
    `UnreachablePointsError` бросается только при обращении именно к такой
    паре, а не при построении матрицы.
    """

    def __init__(
        self,
        index_by_id: dict[uuid.UUID, int],
        travel_minutes: list[list[int | None]],
        distance_km: list[list[Decimal | None]],
    ) -> None:
        self._index_by_id = index_by_id
        self._travel_minutes = travel_minutes
        self._distance_km = distance_km

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        value = self._travel_minutes[self._index_by_id[from_id]][self._index_by_id[to_id]]
        if value is None:
            raise UnreachablePointsError(from_id, to_id)
        return value

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        value = self._distance_km[self._index_by_id[from_id]][self._index_by_id[to_id]]
        if value is None:
            raise UnreachablePointsError(from_id, to_id)
        return value


class RoutingService:
    """Строит матрицу времени/расстояния между точками через OSRM `Table API`.

    Один вызов `build_matrix` — минимум HTTP-запросов на всю матрицу сразу,
    не попарные запросы (см. `docs/ROUTING.md`). Результат не кэшируется
    между вызовами: реальное время в пути может измениться (пробки, ремонт
    дорог), поэтому при перепланировании матрица всегда считается заново, а
    не берётся из предыдущего плана.

    Провайдер (включая публичный demo-сервер OSRM) ограничивает число точек
    в одном `Table`-запросе (`cfg.routing.max_table_coordinates`, измерено
    для `router.project-osrm.org` — ровно 100, превышение даёт `400 TooBig`).
    При большем числе точек матрица собирается несколькими запросами по
    парам блоков точек (см. `_iter_blocks`) и склеивается в одну — ценой
    нескольких HTTP-запросов вместо одного, но без потери полноты матрицы.
    """

    def __init__(self, client: RoutingClient) -> None:
        self._client = client

    async def build_matrix(self, points: Sequence[RoutingPoint]) -> RoutingMatrix:
        if len(points) < 2:
            raise ValueError("Матрица требует минимум 2 точки")

        index_by_id = {point.id: index for index, point in enumerate(points)}
        size = len(points)
        travel_minutes: list[list[int | None]] = [[None] * size for _ in range(size)]
        distance_km: list[list[Decimal | None]] = [[None] * size for _ in range(size)]

        for block in self._iter_blocks(points):
            block_travel, block_distance = await self._fetch_block(block)
            for local_i, point_i in enumerate(block):
                global_i = index_by_id[point_i.id]
                for local_j, point_j in enumerate(block):
                    global_j = index_by_id[point_j.id]
                    travel_minutes[global_i][global_j] = block_travel[local_i][local_j]
                    distance_km[global_i][global_j] = block_distance[local_i][local_j]

        return RoutingMatrix(
            index_by_id=index_by_id, travel_minutes=travel_minutes, distance_km=distance_km
        )

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
        self, points: Sequence[RoutingPoint]
    ) -> tuple[list[list[int | None]], list[list[Decimal | None]]]:
        coordinates = ";".join(f"{point.longitude},{point.latitude}" for point in points)
        url = f"/table/v1/{cfg.routing.profile}/{coordinates}"
        try:
            response = await self._client.get().get(
                url, params={"annotations": "duration,distance"}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise InvalidRoutingResponseError(
                f"Провайдер отклонил запрос ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RoutingUnavailableError("Сервис маршрутизации недоступен") from exc

        if payload.get("code") != "Ok":
            raise InvalidRoutingResponseError(f"Провайдер вернул код {payload.get('code')!r}")

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
