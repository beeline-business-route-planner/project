from dishka import Provider, Scope, provide

from src.core.dgis import DgisMatrixService
from src.core.routing import RoutingService
from src.core.travel_matrix import TravelMatrixService


class TravelMatrixProvider(Provider):
    @provide(scope=Scope.APP)
    def get_travel_matrix_service(
        self, dgis: DgisMatrixService, osrm: RoutingService
    ) -> TravelMatrixService:
        return TravelMatrixService(dgis, osrm)
