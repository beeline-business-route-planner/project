from dishka import Provider, Scope, provide

from src.api.reports.service import DailyReportExportService, DailyReportService
from src.core.db.uow import UnitOfWork
from src.core.s3 import S3ExportDelivery


class ReportsProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_daily_report_service(self, uow: UnitOfWork) -> DailyReportService:
        return DailyReportService(uow)

    @provide(scope=Scope.REQUEST)
    def get_daily_report_export_service(
        self, reports: DailyReportService, delivery: S3ExportDelivery
    ) -> DailyReportExportService:
        return DailyReportExportService(reports, delivery)
