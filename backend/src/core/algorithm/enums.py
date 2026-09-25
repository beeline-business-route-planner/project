import enum


class DistributionMode(enum.StrEnum):
    """Вторичная цель после допустимости и покрытия заявок."""

    MIN_ENGINEERS = "min_engineers"
    BALANCED = "balanced"


class AlgorithmVariant(enum.StrEnum):
    """Реализации initial с общим контрактом."""

    LAYERED_GRAPH = "layered_graph"
    LAYERED_GRAPH_ALNS = "layered_graph_alns"
    LAYERED_GRAPH_GREEDY = "layered_graph_greedy"
    GREEDY = "greedy"
    BASELINE = "baseline"


class DestroyOperator(enum.StrEnum):
    """Destroy-окрестности детерминированного ALNS."""

    SINGLE_ENGINEER = "single_engineer"
    ENGINEER_PAIR = "engineer_pair"
    TIME_WINDOW = "time_window"
    GEOGRAPHIC_CLUSTER = "geographic_cluster"
