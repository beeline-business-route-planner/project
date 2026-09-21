from dishka import Provider, Scope, provide

from src.core.algorithm import AlgorithmService
from src.core.db.uow import UnitOfWork
from src.core.routing import RoutingService


class AlgorithmProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_algorithm_service(self, uow: UnitOfWork, routing: RoutingService) -> AlgorithmService:
        return AlgorithmService(uow, routing)
