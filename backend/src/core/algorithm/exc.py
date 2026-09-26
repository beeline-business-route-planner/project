class AlgorithmError(Exception):
    """Базовая ошибка чистой алгоритмической подсистемы."""


class AlgorithmInputError(AlgorithmError):
    """Переданный snapshot неполон или противоречив."""


class AlgorithmAuditError(AlgorithmError):
    """Рассчитанный результат нарушает жёсткий инвариант."""


class MissingCoordinatesError(AlgorithmInputError):
    """У заявки или стартовой точки инженера нет координат."""
