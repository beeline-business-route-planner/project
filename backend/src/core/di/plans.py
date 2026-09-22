from dishka import Provider, Scope, provide

from src.api.plans.service import PlanService
from src.core.db.uow import UnitOfWork


class PlansProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_plan_service(self, uow: UnitOfWork) -> PlanService:
        return PlanService(uow)
