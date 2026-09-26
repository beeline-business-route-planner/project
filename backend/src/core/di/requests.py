from dishka import Provider, Scope, provide

from src.api.requests.service import RequestService
from src.core.db.uow import UnitOfWork


class RequestsProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_request_service(self, uow: UnitOfWork) -> RequestService:
        return RequestService(uow)
