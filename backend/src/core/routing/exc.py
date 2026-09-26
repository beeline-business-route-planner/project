import uuid


class RoutingUnavailableError(Exception):
    pass


class InvalidRoutingResponseError(Exception):
    pass


class UnreachablePointsError(Exception):
    """Между двумя точками матрицы нет маршрута."""

    def __init__(self, from_id: uuid.UUID, to_id: uuid.UUID) -> None:
        self.from_id = from_id
        self.to_id = to_id
        super().__init__(f"Между точками нет маршрута: {from_id} -> {to_id}")
