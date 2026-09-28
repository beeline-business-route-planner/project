import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from src.config import cfg
from src.core.algorithm.dto import Engineer, Job, PlanningLayer
from src.core.algorithm.exc import AlgorithmInputError


class PlanningRules:
    """Общие для стратегий и аудита правила: допуск инженера, слои заявок, вес приоритета."""

    @staticmethod
    def eligible(engineer: Engineer, job: Job) -> bool:
        """Проверяет доступность инженера, навык и транспортное ограничение заявки."""

        if not engineer.is_available:
            return False
        if job.required_skill not in engineer.skills:
            return False
        return (
            job.required_vehicle_type is None or job.required_vehicle_type == engineer.vehicle_type
        )

    @staticmethod
    def index_layers(
        layers: Sequence[PlanningLayer],
        jobs_by_id: dict[uuid.UUID, Job],
    ) -> dict[uuid.UUID, PlanningLayer]:
        """Сопоставляет каждой заявке её слой и проверяет согласованность слоёв.

        Raises:
            AlgorithmInputError: если опорное время слоя не середина окна, в слое повторяется
                транспорт или заявка не принадлежит ровно одному слою.
        """

        indexed: dict[uuid.UUID, PlanningLayer] = {}
        for layer in layers:
            midpoint = layer.window_start + (layer.window_end - layer.window_start) / 2
            if layer.traffic_reference_at != midpoint:
                raise AlgorithmInputError("traffic_reference_at должен быть серединой окна")
            vehicle_types = [item.vehicle_type for item in layer.matrices]
            if len(vehicle_types) != len(set(vehicle_types)):
                raise AlgorithmInputError("В слое повторяется матрица одного типа транспорта")
            for request_id in layer.request_ids:
                if request_id not in jobs_by_id or request_id in indexed:
                    raise AlgorithmInputError("Слои содержат неизвестную или повторную заявку")
                indexed[request_id] = layer
        if set(indexed) != set(jobs_by_id):
            raise AlgorithmInputError("Каждая заявка должна принадлежать ровно одному слою")
        return indexed

    @staticmethod
    def priority_score(priority: int) -> int:
        """Степенной вес приоритета: авария `w**2`, подключение `w`, ремонт `1`."""

        if priority not in {1, 2, 3}:
            raise AlgorithmInputError("Приоритет заявки должен быть от 1 до 3")
        return cfg.algorithm.priority_tier_weight ** (3 - priority)

    @staticmethod
    def stop_distance(kilometers: Decimal) -> Decimal:
        """Расстояние перехода с точностью хранения остановки (0,01 км).

        Округление на входе, а не на итогах: пробег маршрута и плана — точная сумма
        сохранённых остановок, и сохранённые агрегаты сходятся с маршрутами.
        """

        return kilometers.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
