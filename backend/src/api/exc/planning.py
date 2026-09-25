from src.api.exc.base import http_error


@http_error(
    status_code=422,
    detail="Нужно загрузить хотя бы один Excel-файл",
)
class PlanningFileCountError(Exception):
    pass


@http_error(
    status_code=422,
    detail="Для каждого округа нужна ровно одна таблица заявок и одна таблица инженеров",
)
class PlanningRegionPairError(Exception):
    pass


@http_error(status_code=422, detail="Один или несколько файлов не соответствуют ожидаемому формату")
class PlanningFileValidationError(Exception):
    pass


@http_error(
    status_code=409, detail="В таблицах есть повторяющиеся или уже загруженные номера заявок"
)
class RepeatedRequestError(Exception):
    pass


@http_error(
    status_code=422, detail="Не удалось определить координаты одного или нескольких адресов"
)
class PlanningAddressNotFound(Exception):
    pass


@http_error(status_code=502, detail="Сервис геокодирования временно недоступен")
class PlanningGeocodingUnavailable(Exception):
    pass


@http_error(status_code=502, detail="Хранилище файлов временно недоступно")
class PlanningStorageUnavailable(Exception):
    pass


@http_error(status_code=502, detail="Сервис маршрутизации временно недоступен")
class PlanningRoutingUnavailable(Exception):
    pass


@http_error(status_code=502, detail="Сервис маршрутизации вернул некорректный ответ")
class PlanningInvalidRoutingResponse(Exception):
    pass


@http_error(status_code=422, detail="Между двумя точками маршрута не найден путь")
class PlanningUnreachablePoints(Exception):
    pass


@http_error(status_code=422, detail="У заявки или инженера не определены координаты")
class PlanningMissingCoordinates(Exception):
    pass
