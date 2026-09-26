from dishka import Provider, Scope, provide

from src.api.plans.service import PlanExportService, PlanService
from src.core.db.uow import UnitOfWork
from src.core.s3 import S3Storage


class PlansProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_plan_service(self, uow: UnitOfWork) -> PlanService:
        return PlanService(uow)

    @provide(scope=Scope.REQUEST)
    def get_plan_export_service(self, plans: PlanService, storage: S3Storage) -> PlanExportService:
        return PlanExportService(plans, storage)
