from dishka import Provider, Scope, provide

from src.api.planning.service import PlanningService
from src.core.algorithm import AlgorithmService
from src.core.db.uow import UnitOfWork
from src.core.geocoding import GeocodingService
from src.core.s3 import S3Storage
from src.core.travel_matrix import TravelMatrixService


class PlanningProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_planning_service(
        self,
        uow: UnitOfWork,
        geocoding: GeocodingService,
        storage: S3Storage,
        algorithm: AlgorithmService,
        travel_matrix: TravelMatrixService,
    ) -> PlanningService:
        return PlanningService(uow, geocoding, storage, algorithm, travel_matrix)
