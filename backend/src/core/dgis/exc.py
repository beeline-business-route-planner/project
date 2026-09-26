import uuid


class DgisUnavailableError(Exception):
    pass


class InvalidDgisResponseError(Exception):
    pass


class DgisUnreachablePointsError(Exception):
    def __init__(self, from_id: uuid.UUID, to_id: uuid.UUID) -> None:
        self.from_id = from_id
        self.to_id = to_id
        super().__init__(f"Между точками нет маршрута: {from_id} -> {to_id}")
