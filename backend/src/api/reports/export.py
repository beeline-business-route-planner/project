import re
from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


class DailyReportZipBuilder:
    """Собирает детерминированный ZIP из готовых PDF без локальных файлов."""

    @staticmethod
    def build(planning_date: date, files: dict[str, bytes], region_codes: tuple[str, ...]) -> bytes:
        expected = {"summary.pdf", *(f"{code}.pdf" for code in region_codes)}
        if len(expected) != len(region_codes) + 1 or set(files) != expected:
            raise ValueError("Неверный набор PDF для дневного отчёта")
        output = BytesIO()
        folder = f"daily-report-{planning_date.isoformat()}"
        with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
            for filename in sorted(files, key=lambda item: (item != "summary.pdf", item)):
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.pdf", filename):
                    raise ValueError("Некорректное имя PDF в дневном отчёте")
                data = files[filename]
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Неверный PDF в дневном отчёте")
                info = ZipInfo(f"{folder}/{filename}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)
        return output.getvalue()
