from src.api.exc.base import http_error


@http_error(status_code=404, detail="Заявка не найдена")
class RequestNotFoundError(Exception):
    pass
