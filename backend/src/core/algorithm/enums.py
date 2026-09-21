import enum


class DistributionMode(enum.StrEnum):
    """Режим сортировки инженеров в `DistributionPlanner` (см. `docs/ALGORITHM.md`)."""

    MIN_ENGINEERS = "min_engineers"
    BALANCED = "balanced"
