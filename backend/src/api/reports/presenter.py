from decimal import Decimal

from src.api.reports.dto import (
    RegionReportSnapshot,
    ReportEngineer,
    ReportMetrics,
    ReportPlanChange,
    ReportPlanVersion,
)


class ReportPresenter:
    """Считает агрегаты и краткие изменения из готовых снимков отчёта."""

    @staticmethod
    def metrics(
        engineers: tuple[ReportEngineer, ...], assigned_count: int, unassigned_count: int
    ) -> ReportMetrics:
        used = tuple(item for item in engineers if item.stops)
        available = tuple(item for item in engineers if item.is_available)
        return ReportMetrics(
            requests_count=assigned_count + unassigned_count,
            assigned_count=assigned_count,
            unassigned_count=unassigned_count,
            engineers_count=len(engineers),
            engineers_used_count=len(used),
            mileage_km=sum((item.mileage_km for item in engineers), Decimal("0")),
            work_minutes=sum(item.work_minutes for item in engineers),
            travel_minutes=sum(item.travel_minutes for item in engineers),
            utilization_with_travel=ReportPresenter._average(
                tuple(item.utilization_with_travel for item in available)
            ),
            utilization_without_travel=ReportPresenter._average(
                tuple(item.utilization_without_travel for item in available)
            ),
        )

    @staticmethod
    def summary(regions: tuple[RegionReportSnapshot, ...]) -> ReportMetrics:
        metrics = tuple(item.metrics for item in regions)
        available = tuple(
            engineer for region in regions for engineer in region.engineers if engineer.is_available
        )
        return ReportMetrics(
            requests_count=sum(item.requests_count for item in metrics),
            assigned_count=sum(item.assigned_count for item in metrics),
            unassigned_count=sum(item.unassigned_count for item in metrics),
            engineers_count=sum(item.engineers_count for item in metrics),
            engineers_used_count=sum(item.engineers_used_count for item in metrics),
            mileage_km=sum((item.mileage_km for item in metrics), Decimal("0")),
            work_minutes=sum(item.work_minutes for item in metrics),
            travel_minutes=sum(item.travel_minutes for item in metrics),
            utilization_with_travel=ReportPresenter._average(
                tuple(item.utilization_with_travel for item in available)
            ),
            utilization_without_travel=ReportPresenter._average(
                tuple(item.utilization_without_travel for item in available)
            ),
        )

    @staticmethod
    def changes(plans: tuple[ReportPlanVersion, ...]) -> tuple[ReportPlanChange, ...]:
        return tuple(
            ReportPlanChange(
                previous_plan_id=previous.id,
                plan_id=current.id,
                assigned_delta=current.assigned_count - previous.assigned_count,
                unassigned_delta=current.unassigned_count - previous.unassigned_count,
                engineers_used_delta=current.engineers_used_count - previous.engineers_used_count,
                mileage_delta_km=current.mileage_km - previous.mileage_km,
            )
            for previous, current in zip(plans, plans[1:], strict=False)
        )

    @staticmethod
    def _average(values: tuple[Decimal, ...]) -> Decimal:
        if not values:
            return Decimal("0")
        return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.01"))
