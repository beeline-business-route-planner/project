from src.api.exc.base import http_error


@http_error(status_code=404, detail="Инженер не найден")
class EngineerNotFoundError(Exception):
    pass
