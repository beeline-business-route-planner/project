from src.api.exc.base import http_error


@http_error(status_code=404, detail="Заявка не найдена")
class RequestNotFoundError(Exception):
    pass


@http_error(status_code=409, detail="Отменить заявку можно только внештатным событием")
class RequestCancelViaStatusError(Exception):
    pass


@http_error(status_code=409, detail="Заявка отменена, её статус больше не меняется")
class RequestAlreadyCancelledError(Exception):
    pass
