from src.api.exc.base import http_error


@http_error(status_code=404, detail="План не найден")
class PlanNotFoundError(Exception):
    pass


@http_error(status_code=409, detail="План уже рассмотрен")
class PlanNotPendingError(Exception):
    pass


@http_error(status_code=409, detail="План относится к другому рабочему дню")
class PlanWrongDayError(Exception):
    pass


@http_error(status_code=409, detail="Время утверждения первичного плана истекло")
class InitialPlanExpiredError(Exception):
    pass


@http_error(status_code=409, detail="Рабочий план изменился после расчёта")
class PlanBaseChangedError(Exception):
    pass


@http_error(status_code=409, detail="Состояние заявок или инженеров изменилось после расчёта")
class PlanStateChangedError(Exception):
    pass


@http_error(status_code=409, detail="Изменяемая остановка уже началась")
class PlanStopAlreadyStartedError(Exception):
    pass
