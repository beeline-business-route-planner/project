import enum


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
