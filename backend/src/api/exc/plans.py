from src.api.exc.base import http_error


@http_error(status_code=404, detail="План не найден")
class PlanNotFoundError(Exception):
    pass
