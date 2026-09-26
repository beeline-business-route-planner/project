from dishka import Provider, Scope, provide

from src.api.reports.service import DailyReportService
from src.core.db.uow import UnitOfWork


class ReportsProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_daily_report_service(self, uow: UnitOfWork) -> DailyReportService:
        return DailyReportService(uow)
