"""Геометрия перехода между остановками через Routing API 2ГИС."""

import math
from dataclasses import dataclass

import httpx

from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.dgis.client import DgisClient
from src.core.dgis.exc import DgisUnavailableError, InvalidDgisResponseError


@dataclass(frozen=True)
class RouteLeg:
    coordinates: tuple[tuple[float, float], ...]
    distance_meters: int
    duration_seconds: int


class DgisRouteService:
    """Запрашивает линию пути для одного типа транспорта, не меняя порядок точек."""

    def __init__(self, client: DgisClient) -> None:
        self._client = client

    async def build_leg(
        self,
        start: tuple[float, float],
        finish: tuple[float, float],
        vehicle_type: VehicleType,
    ) -> RouteLeg:
        if not cfg.dgis.api_key:
            raise DgisUnavailableError("Не задан ключ 2ГИС")
        if vehicle_type == VehicleType.PUBLIC_TRANSPORT:
            path = "/public_transport/2.0"
            payload = {
                "source": {"point": {"lon": start[0], "lat": start[1]}},
                "target": {"point": {"lon": finish[0], "lat": finish[1]}},
                "transport": [
                    "metro",
                    "bus",
                    "tram",
                    "trolleybus",
                    "shuttle_bus",
                    "suburban_train",
                    "mcc",
                    "mcd",
                    "pedestrian",
                ],
                "max_result_count": 1,
            }
        else:
            path = "/routing/7.0.0/global"
            transport = {
                VehicleType.CAR: "driving",
                VehicleType.PEDESTRIAN: "walking",
                VehicleType.BICYCLE: "bicycle",
            }[vehicle_type]
            payload = {
                "points": [
                    {"type": "stop", "lon": start[0], "lat": start[1]},
                    {"type": "stop", "lon": finish[0], "lat": finish[1]},
                ],
                "transport": transport,
                "output": "detailed",
            }
        try:
            response = await self._client.get().post(
                path, params={"key": cfg.dgis.api_key}, json=payload
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPError as exc:
            raise DgisUnavailableError("Routing API 2ГИС недоступен") from exc
        except ValueError as exc:
            raise InvalidDgisResponseError("2ГИС вернул невалидный JSON маршрута") from exc

        if vehicle_type == VehicleType.PUBLIC_TRANSPORT:
            if not isinstance(raw, list) or not raw:
                raise InvalidDgisResponseError("2ГИС не построил маршрут транспорта")
            option = raw[0]
            geometry = self._public_transport_geometry(option)
        else:
            if not isinstance(raw, dict) or raw.get("status") != "OK":
                raise InvalidDgisResponseError("2ГИС не построил маршрут")
            options = raw.get("result")
            if not isinstance(options, list) or not options:
                raise InvalidDgisResponseError("2ГИС не вернул вариант маршрута")
            option = options[0]
            geometry = self._street_geometry(option)

        if not isinstance(option, dict):
            raise InvalidDgisResponseError("Некорректный вариант маршрута 2ГИС")
        distance = option.get("total_distance")
        duration = option.get("total_duration")
        if (
            len(geometry) < 2
            or not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or distance < 0
            or duration < 0
        ):
            raise InvalidDgisResponseError("2ГИС вернул неполную геометрию маршрута")
        return RouteLeg(tuple(geometry), int(distance), int(duration))

    @classmethod
    def _street_geometry(cls, option: object) -> list[tuple[float, float]]:
        if not isinstance(option, dict) or not isinstance(option.get("maneuvers"), list):
            raise InvalidDgisResponseError("Некорректные манёвры маршрута 2ГИС")
        result: list[tuple[float, float]] = []
        for maneuver in option["maneuvers"]:
            if not isinstance(maneuver, dict):
                continue
            path = maneuver.get("outcoming_path")
            if isinstance(path, dict):
                before = len(result)
                cls._append_selections(result, path.get("geometry"))
                if path.get("distance", 0) and len(result) == before:
                    raise InvalidDgisResponseError("2ГИС не вернул геометрию участка")
        return result

    @classmethod
    def _public_transport_geometry(cls, option: object) -> list[tuple[float, float]]:
        if not isinstance(option, dict) or not isinstance(option.get("movements"), list):
            raise InvalidDgisResponseError("Некорректные пересадки маршрута 2ГИС")
        result: list[tuple[float, float]] = []
        for movement in option["movements"]:
            if not isinstance(movement, dict):
                continue
            alternatives = movement.get("alternatives")
            before = len(result)
            if (
                isinstance(alternatives, list)
                and alternatives
                and isinstance(alternatives[0], dict)
            ):
                cls._append_selections(result, alternatives[0].get("geometry"))
            if movement.get("distance", 0) and len(result) == before:
                raise InvalidDgisResponseError("2ГИС не вернул геометрию пересадки")
        return result

    @classmethod
    def _append_selections(cls, result: list[tuple[float, float]], items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            selection = item.get("selection")
            if not isinstance(selection, str):
                continue
            points = cls._parse_linestring(selection)
            result.extend(points[1:] if result and points and result[-1] == points[0] else points)

    @staticmethod
    def _parse_linestring(value: str) -> list[tuple[float, float]]:
        if not value.startswith("LINESTRING(") or not value.endswith(")"):
            raise InvalidDgisResponseError("Некорректная геометрия маршрута 2ГИС")
        coordinates: list[tuple[float, float]] = []
        for pair in value[len("LINESTRING(") : -1].split(","):
            parts = pair.strip().split()
            if len(parts) < 2:
                raise InvalidDgisResponseError("Некорректная точка маршрута 2ГИС")
            try:
                longitude, latitude = float(parts[0]), float(parts[1])
            except ValueError as exc:
                raise InvalidDgisResponseError("Некорректная точка маршрута 2ГИС") from exc
            if not (
                math.isfinite(longitude)
                and math.isfinite(latitude)
                and -180 <= longitude <= 180
                and -90 <= latitude <= 90
            ):
                raise InvalidDgisResponseError("Некорректная точка маршрута 2ГИС")
            coordinates.append((longitude, latitude))
        return coordinates
