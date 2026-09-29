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


@http_error(status_code=422, detail="Дата заявок в таблице не совпадает с сегодняшним рабочим днём")
class PlanningWrongDateError(Exception):
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


@http_error(status_code=422, detail="У заявки или инженера не определены координаты")
class PlanningMissingCoordinates(Exception):
    pass


@http_error(status_code=409, detail="У округа нет утверждённого рабочего плана на этот день")
class PlanningCurrentPlanMissing(Exception):
    pass


@http_error(status_code=409, detail="У округа уже есть ожидающее решение событие")
class PlanningPendingEventExists(Exception):
    pass


@http_error(status_code=404, detail="Цель события не найдена в текущем плане округа")
class PlanningEventTargetMissing(Exception):
    pass


@http_error(status_code=409, detail="Заявка уже отменена")
class PlanningRequestAlreadyCancelled(Exception):
    pass


@http_error(status_code=409, detail="Заявка уже в работе или выполнена, её нельзя отменить")
class PlanningRequestAlreadyStarted(Exception):
    pass


@http_error(status_code=409, detail="Инженер уже находится в запрошенном состоянии")
class PlanningEngineerStateConflict(Exception):
    pass


@http_error(status_code=409, detail="Срочная заявка с этим внешним ID уже существует")
class PlanningUrgentRequestExists(Exception):
    pass


@http_error(
    status_code=422,
    detail="Некорректный тип, норматив, навык или окно срочной заявки",
)
class PlanningUrgentRequestInvalid(Exception):
    pass


@http_error(status_code=404, detail="Загрузка для ручного планирования не найдена")
class ManualUploadNotFound(Exception):
    pass


@http_error(status_code=409, detail="Исходный план изменился или уже рассмотрен")
class ManualSourceConflict(Exception):
    pass


@http_error(status_code=422, detail="Ручной маршрут нарушает ограничения планирования")
class ManualRouteInvalid(Exception):
    def __init__(self, issues: list[dict[str, str | None]] | None = None) -> None:
        super().__init__("Ручной маршрут нарушает ограничения планирования")
        self.details = {"issues": issues} if issues else {}
