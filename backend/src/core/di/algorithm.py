from dishka import Provider, Scope, provide

from src.core.algorithm import AlgorithmService


class AlgorithmProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_algorithm_service(self) -> AlgorithmService:
        return AlgorithmService()
