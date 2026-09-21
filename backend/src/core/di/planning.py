from dishka import Provider, Scope, provide

from src.core.db.uow import UnitOfWork
from src.core.geocoding import GeocodingService
from src.core.s3 import S3Storage
from src.core.services import AlgorithmService, PlanningService


class PlanningProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_planning_service(
        self,
        uow: UnitOfWork,
        geocoding: GeocodingService,
        storage: S3Storage,
        algorithm: AlgorithmService,
    ) -> PlanningService:
        return PlanningService(uow, geocoding, storage, algorithm)
