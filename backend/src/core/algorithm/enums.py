import enum


class DistributionMode(enum.StrEnum):
    """Вторичная цель после допустимости и покрытия заявок."""

    MIN_ENGINEERS = "min_engineers"
    BALANCED = "balanced"


class AlgorithmVariant(enum.StrEnum):
    """Реализации initial с общим контрактом."""

    LAYERED_GRAPH = "layered_graph"
    GREEDY = "greedy"
    BASELINE = "baseline"
