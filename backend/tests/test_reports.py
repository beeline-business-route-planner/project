from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from beeline_backend.application.contracts import DayReport, ReportAssignment
from beeline_backend.infrastructure.reports import PdfReportRenderer, XlsxReportRenderer


def test_xlsx_and_pdf_accept_timezone_aware_report_model(tmp_path: Path) -> None:
    report = DayReport(
        report_version="test-v1",
        plan_id=uuid4(),
        scenario="Восток",
        planning_date=date(2026, 8, 17),
        generated_at=datetime(2026, 8, 17, 8, tzinfo=UTC),
        interim=True,
        assignments=[
            ReportAssignment(
                engineer="Инженер 1",
                position=1,
                request_external_id="REQ-1",
                address="Москва",
                planned_start=datetime(2026, 8, 17, 6, tzinfo=UTC),
                planned_finish=datetime(2026, 8, 17, 7, tzinfo=UTC),
                confirmed_status="NOT_SENT",
                actual_start=None,
                actual_finish=None,
                fact_source=None,
                distance_meters=1200,
            )
        ],
        metrics={"assigned_count": 1},
    )
    xlsx_path = tmp_path / "report.xlsx"
    pdf_path = tmp_path / "report.pdf"

    XlsxReportRenderer().render(report, xlsx_path)
    PdfReportRenderer().render(report, pdf_path)

    workbook = load_workbook(xlsx_path, data_only=True)
    sheet = workbook["Итог дня"]
    assert sheet["E7"].value == datetime(2026, 8, 17, 9)
    assert sheet["H7"].value == "нет данных"
    assert pdf_path.read_bytes().startswith(b"%PDF")
