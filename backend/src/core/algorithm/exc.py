from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.algorithm.dto import ManualDiagnosis


class AlgorithmError(Exception):
    """Базовая ошибка чистой алгоритмической подсистемы."""


class AlgorithmInputError(AlgorithmError):
    """Переданный snapshot неполон или противоречив."""


class AlgorithmAuditError(AlgorithmError):
    """Рассчитанный результат нарушает жёсткий инвариант."""


class ManualRouteViolationError(AlgorithmInputError):
    """Ручной маршрут нарушает ограничения; `diagnosis` говорит, где и почему."""

    def __init__(self, diagnosis: ManualDiagnosis) -> None:
        super().__init__("Ручной маршрут нарушает ограничения планирования")
        self.diagnosis = diagnosis


class MissingCoordinatesError(AlgorithmInputError):
    """У заявки или стартовой точки инженера нет координат."""
