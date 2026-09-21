from abc import ABC, abstractmethod
from typing import ClassVar

from src.core.algorithm.models import EngineerPlanningContext, Route


class PlanningAlgorithm(ABC):
    """Общий интерфейс стратегии секвенирования маршрута одного инженера.

    Три метода отражают три сценария планирования (`Plan.kind` в `DATABASE.md`):
    первичное планирование по утренней выгрузке, ручной пересчёт без новых
    данных и пересчёт из-за внештатного события. Сейчас реализован только
    `plan_initial` — остальные два объявлены как часть контракта заранее, чтобы
    конкретные стратегии (`src/core/algorithm/strategies/`) дорабатывались под
    единую сигнатуру, а не расходились в названии метода по мере реализации.
    См. `docs/ALGORITHM.md`.
    """

    name: ClassVar[str]
    slug: ClassVar[str]
    DEFAULT_BUDGET_SECONDS: ClassVar[float]

    @abstractmethod
    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        """Строит маршрут инженера с нуля по его пулу допустимых заявок.

        Args:
            context: инженер, его пул заявок и матрица времени/расстояния.
            budget_seconds: сколько секунд стратегия может потратить на поиск.

        Returns:
            Маршрут — упорядоченный список остановок среди `context.jobs`. Не
            обязательно все заявки пула поместятся — что делать с
            непомещёнными, решает `DistributionPlanner`, не сама стратегия.
        """

    def plan_replan(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        """Пересчитывает маршрут при ручном пересчёте без новых данных (`manual_replan`).

        Raises:
            NotImplementedError: сценарий пока не реализован ни в одной
                стратегии — уже состоявшиеся/прошедшие остановки
                (`PlanStop.is_locked`) нужно перенести без изменений,
                пересчитать только то, что ещё впереди по времени.
        """
        raise NotImplementedError(f"{self.slug}: manual_replan ещё не реализован")

    def plan_on_event(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        """Пересчитывает маршрут из-за внештатного события (`event_replan`).

        Raises:
            NotImplementedError: сценарий пока не реализован ни в одной
                стратегии — нужно учитывать конкретный `ReplanningEventType`
                (срочная заявка/отмена/недоступность инженера).
        """
        raise NotImplementedError(f"{self.slug}: event_replan ещё не реализован")
