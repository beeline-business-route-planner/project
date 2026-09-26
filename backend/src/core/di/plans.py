from dishka import Provider, Scope, provide

from src.api.plans.service import PlanExportService, PlanRouteService, PlanService
from src.core.db.uow import UnitOfWork
from src.core.dgis.route import DgisRouteService
from src.core.s3 import S3ExportDelivery


class PlansProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_plan_service(self, uow: UnitOfWork) -> PlanService:
        return PlanService(uow)

    @provide(scope=Scope.REQUEST)
    def get_plan_route_service(
        self, plans: PlanService, routes: DgisRouteService
    ) -> PlanRouteService:
        return PlanRouteService(plans, routes)

    @provide(scope=Scope.REQUEST)
    def get_plan_export_service(
        self, plans: PlanService, delivery: S3ExportDelivery
    ) -> PlanExportService:
        return PlanExportService(plans, delivery)
