import enum


class DistributionMode(enum.StrEnum):
    """Вторичная цель после допустимости и покрытия заявок."""

    MIN_ENGINEERS = "min_engineers"
    BALANCED = "balanced"


class AlgorithmVariant(enum.StrEnum):
    """Реализации initial с общим контрактом."""

    LAYERED_GRAPH = "layered_graph"
    LNS = "lns"
    GREEDY = "greedy"
    BASELINE = "baseline"


class RuinOperator(enum.StrEnum):
    """Операторы разрушения плана в LNS."""

    RANDOM = "random"
    RELATED = "related"
    ROUTE = "route"
    TIME_WINDOW = "time_window"
    STRING = "string"
    WORST = "worst"
