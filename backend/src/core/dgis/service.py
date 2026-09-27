import asyncio
import math
import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.dgis.client import DgisClient
from src.core.dgis.dto import DgisPoint
from src.core.dgis.exc import (
    DgisUnavailableError,
    InvalidDgisResponseError,
)


class DgisMatrix:
    """Матрица 2ГИС с учётом пробок, адресуемая ID доменных точек."""

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
        """Время в пути; `None` — 2ГИС не нашёл маршрут между точками."""

        return self._travel_minutes[self._index_by_id[from_id]][self._index_by_id[to_id]]

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal | None:
        return self._distance_km[self._index_by_id[from_id]][self._index_by_id[to_id]]


class DgisMatrixService:
    """Строит матрицы 2ГИС минимальным числом HTTP-блоков в пределах лимита ключа."""

    def __init__(self, client: DgisClient) -> None:
        self._client = client

    async def build_matrix(
        self,
        points: Sequence[DgisPoint],
        vehicle_type: VehicleType,
        departure_at: datetime | None = None,
        source_ids: frozenset[uuid.UUID] | None = None,
        target_ids: frozenset[uuid.UUID] | None = None,
    ) -> DgisMatrix:
        if not points:
            raise ValueError("Матрица требует хотя бы одну точку")
        if not cfg.dgis.api_key:
            raise DgisUnavailableError("Не задан dgis.api_key")

        index_by_id = {point.id: index for index, point in enumerate(points)}
        if len(index_by_id) != len(points):
            raise ValueError("Идентификаторы точек матрицы должны быть уникальны")
        requested_ids = (source_ids or frozenset()) | (target_ids or frozenset())
        if requested_ids - set(index_by_id):
            raise ValueError("Источники и цели должны присутствовать в points")
        selected_sources = [
            index
            for index, point in enumerate(points)
            if source_ids is None or point.id in source_ids
        ]
        selected_targets = [
            index
            for index, point in enumerate(points)
            if target_ids is None or point.id in target_ids
        ]
        if not selected_sources or not selected_targets:
            raise ValueError("Матрица требует непустые sources и targets")

        size = len(points)
        travel_minutes: list[list[int | None]] = [[None] * size for _ in range(size)]
        distance_km: list[list[Decimal | None]] = [[None] * size for _ in range(size)]
        for source_indexes, target_indexes in self._matrix_blocks(
            selected_sources, selected_targets
        ):
            routes, source_by_local, target_by_local = await self._fetch_block(
                points,
                source_indexes,
                target_indexes,
                departure_at,
                self._transport(vehicle_type),
            )
            self._merge_block(
                routes,
                source_by_local,
                target_by_local,
                travel_minutes,
                distance_km,
            )
        return DgisMatrix(index_by_id, travel_minutes, distance_km)

    @staticmethod
    def _transport(vehicle_type: VehicleType) -> str:
        match vehicle_type:
            case VehicleType.CAR:
                return "driving"
            case VehicleType.PEDESTRIAN:
                return "walking"
            case VehicleType.BICYCLE:
                return "bicycle"
            case VehicleType.PUBLIC_TRANSPORT:
                return "public_transport"

    async def _fetch_block(
        self,
        points: Sequence[DgisPoint],
        source_indexes: list[int],
        target_indexes: list[int],
        departure_at: datetime | None,
        transport: str,
    ) -> tuple[list[object], dict[int, int], dict[int, int]]:
        block_indexes = list(dict.fromkeys([*source_indexes, *target_indexes]))
        local_by_global = {
            global_index: local_index for local_index, global_index in enumerate(block_indexes)
        }
        source_by_local = {
            local_by_global[global_index]: global_index for global_index in source_indexes
        }
        target_by_local = {
            local_by_global[global_index]: global_index for global_index in target_indexes
        }
        payload: dict[str, object] = {
            "points": [
                {"lat": float(points[index].latitude), "lon": float(points[index].longitude)}
                for index in block_indexes
            ],
            "sources": list(source_by_local),
            "targets": list(target_by_local),
            "transport": transport,
        }
        if departure_at is not None:
            aware_departure = (
                departure_at.replace(tzinfo=ZoneInfo("Europe/Moscow"))
                if departure_at.tzinfo is None
                else departure_at
            )
            payload["start_time"] = aware_departure.isoformat()
            if transport in {"driving", "taxi", "truck", "motorcycle"}:
                payload["type"] = "statistics"
        if transport == "public_transport":
            payload["public_transport_params"] = {
                "transport": cfg.dgis.public_transport_types,
                "enable_schedule": departure_at is not None,
            }
        try:
            response = await self._post_matrix(payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise DgisUnavailableError("Исчерпан лимит запросов 2ГИС") from exc
            raise InvalidDgisResponseError(
                f"2ГИС отклонил запрос со статусом {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DgisUnavailableError("2ГИС Distance Matrix API недоступен") from exc
        except ValueError as exc:
            raise InvalidDgisResponseError("2ГИС вернул невалидный JSON") from exc

        routes = body.get("routes") if isinstance(body, dict) else None
        if not isinstance(routes, list):
            raise InvalidDgisResponseError("В ответе 2ГИС отсутствует массив routes")
        return routes, source_by_local, target_by_local

    async def _post_matrix(self, payload: dict[str, object]) -> httpx.Response:
        """Отправляет запрос матрицы; при 429 тарифа повторяет с растущей паузой.

        Запрос идемпотентен, поэтому повтор безопасен; число попыток и пауза — в конфиге.
        """

        delay = cfg.dgis.rate_limit_backoff_seconds
        for _ in range(cfg.dgis.rate_limit_retries):
            response = await self._client.get().post(
                "/get_dist_matrix",
                params={"key": cfg.dgis.api_key, "version": cfg.dgis.api_version},
                json=payload,
            )
            if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
                return response
            await asyncio.sleep(delay)
            delay *= 2
        return await self._client.get().post(
            "/get_dist_matrix",
            params={"key": cfg.dgis.api_key, "version": cfg.dgis.api_version},
            json=payload,
        )

    def _merge_block(
        self,
        routes: list[object],
        source_by_local: dict[int, int],
        target_by_local: dict[int, int],
        travel_minutes: list[list[int | None]],
        distance_km: list[list[Decimal | None]],
    ) -> None:
        seen_pairs: set[tuple[int, int]] = set()
        for raw_route in routes:
            if not isinstance(raw_route, dict):
                raise InvalidDgisResponseError("Некорректная строка routes в ответе 2ГИС")
            source_id = raw_route.get("source_id")
            target_id = raw_route.get("target_id")
            if not isinstance(source_id, int) or not isinstance(target_id, int):
                raise InvalidDgisResponseError("2ГИС не вернул индексы пары маршрута")
            if source_id not in source_by_local or target_id not in target_by_local:
                raise InvalidDgisResponseError("2ГИС вернул индексы вне запрошенного блока")
            pair = (source_id, target_id)
            if pair in seen_pairs:
                raise InvalidDgisResponseError("2ГИС вернул дубликат пары маршрута")
            seen_pairs.add(pair)
            # Кроме FAIL, 2ГИС возвращает, например, PLATFORMS_NOT_FOUND с нулевыми
            # duration/distance: это отсутствие маршрута, а не мгновенный переезд.
            if raw_route.get("status") != "OK":
                continue
            duration = raw_route.get("duration")
            distance = raw_route.get("distance")
            if not isinstance(duration, int | float) or not isinstance(distance, int | float):
                raise InvalidDgisResponseError("2ГИС вернул некорректные duration/distance")
            global_source = source_by_local[source_id]
            global_target = target_by_local[target_id]
            travel_minutes[global_source][global_target] = math.ceil(duration / 60)
            distance_km[global_source][global_target] = Decimal(str(distance)) / Decimal("1000")

        expected_pairs = len(source_by_local) * len(target_by_local)
        if len(seen_pairs) != expected_pairs:
            raise InvalidDgisResponseError("2ГИС вернул неполную матрицу")

    @staticmethod
    def _matrix_blocks(
        source_indexes: list[int], target_indexes: list[int]
    ) -> list[tuple[list[int], list[int]]]:
        """Режет матрицу на блоки в пределах тарифа 2ГИС: источники × цели одного запроса."""

        max_sources = cfg.dgis.max_matrix_sources
        max_targets = cfg.dgis.max_matrix_targets
        if max_sources < 1 or max_targets < 1:
            raise ValueError("Лимиты матрицы 2ГИС должны быть положительными")
        return [
            (
                source_indexes[source_start : source_start + max_sources],
                target_indexes[target_start : target_start + max_targets],
            )
            for target_start in range(0, len(target_indexes), max_targets)
            for source_start in range(0, len(source_indexes), max_sources)
        ]
