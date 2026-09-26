from dishka import Provider, Scope, provide

from src.api.engineers.service import EngineerService
from src.core.db.uow import UnitOfWork


class EngineersProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_engineer_service(self, uow: UnitOfWork) -> EngineerService:
        return EngineerService(uow)
