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


class ManualIssueCode(enum.StrEnum):
    """Почему заявка в ручном маршруте не может быть выполнена."""

    UNKNOWN_REQUEST = "unknown_request"
    DUPLICATE_REQUEST = "duplicate_request"
    UNKNOWN_ENGINEER = "unknown_engineer"
    ENGINEER_UNAVAILABLE = "engineer_unavailable"
    SKILL = "skill"
    VEHICLE = "vehicle"
    WINDOW_ORDER = "window_order"
    NO_ROUTE = "no_route"
    WINDOW_PASSED = "window_passed"
    LATE = "late"
    SHIFT_END = "shift_end"
