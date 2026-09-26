class AddressNotFoundError(Exception):
    def __init__(self, address: str) -> None:
        self.address = address
        super().__init__(f"Координаты адреса не найдены: {address}")


class GeocodingUnavailableError(Exception):
    pass
