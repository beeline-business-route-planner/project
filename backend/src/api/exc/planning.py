from src.api.exc.base import Base


class InvalidPlanningFileCount(Base):
    status_code = 422
    detail = "Нужно загрузить ненулевое чётное количество Excel-файлов"


class InvalidPlanningRegionPair(Base):
    status_code = 422
    detail = "Для каждого округа нужна ровно одна таблица заявок и одна таблица инженеров"


class InvalidPlanningFile(Base):
    status_code = 422
    detail = "Один или несколько файлов не соответствуют ожидаемому формату"


class RepeatedPlanningRequest(Base):
    status_code = 409
    detail = "В таблицах есть повторяющиеся или уже загруженные номера заявок"


class PlanningAddressNotFound(Base):
    status_code = 422
    detail = "Не удалось определить координаты одного или нескольких адресов"


class PlanningGeocodingUnavailable(Base):
    status_code = 502
    detail = "Сервис геокодирования временно недоступен"
