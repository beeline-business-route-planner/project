from src.api.exc.base import http_error


@http_error(status_code=500, detail="Не удалось сформировать дневной отчёт")
class DailyReportGenerationError(Exception):
    pass


@http_error(status_code=502, detail="Хранилище экспорта недоступно")
class DailyReportStorageError(Exception):
    pass
