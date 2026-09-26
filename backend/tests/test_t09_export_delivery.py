"""T09: ZIP-структура, временная S3-доставка и контролируемые ошибки."""

import io
import unittest
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zipfile import ZipFile

from botocore.exceptions import ClientError

from src.api.exc.reports import DailyReportGenerationError, DailyReportStorageError
from src.api.reports.export import DailyReportZipBuilder
from src.api.reports.service import DailyReportExportService
from src.config import cfg
from src.config.config import S3Config
from src.core.db.enums import Region
from src.core.s3 import (
    ExportDownload,
    ExportKind,
    ExportTooLargeError,
    S3Client,
    S3ExportDelivery,
)
from src.core.s3.exc import S3UnavailableError
from src.core.s3.service import S3Storage


class DailyReportZipTest(unittest.TestCase):
    def test_archive_contains_exactly_regions_and_summary_with_stable_names(self) -> None:
        files = {
            "yugo_vostok.pdf": b"%PDF-1.4\nsecond",
            "summary.pdf": b"%PDF-1.4\nsummary",
            "vostok.pdf": b"%PDF-1.4\nfirst",
        }
        planning_date = date(2026, 9, 26)
        first = DailyReportZipBuilder.build(
            planning_date, files, region_codes=("vostok", "yugo_vostok")
        )
        second = DailyReportZipBuilder.build(
            planning_date, dict(reversed(list(files.items()))), ("vostok", "yugo_vostok")
        )
        self.assertEqual(first, second)
        with ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "daily-report-2026-09-26/summary.pdf",
                    "daily-report-2026-09-26/vostok.pdf",
                    "daily-report-2026-09-26/yugo_vostok.pdf",
                ],
            )
            self.assertEqual(archive.read(archive.namelist()[0]), files["summary.pdf"])

    def test_rejects_missing_summary_and_unsafe_name(self) -> None:
        with self.assertRaises(ValueError):
            DailyReportZipBuilder.build(date(2026, 9, 26), {"vostok.pdf": b"%PDF-1.4"}, ("vostok",))
        with self.assertRaises(ValueError):
            DailyReportZipBuilder.build(
                date(2026, 9, 26),
                {"summary.pdf": b"%PDF-1.4", "../other.pdf": b"%PDF-1.4"},
                ("vostok",),
            )
        with self.assertRaises(ValueError):
            DailyReportZipBuilder.build(
                date(2026, 9, 26),
                {"summary.pdf": b"%PDF-1.4", "other.pdf": b"%PDF-1.4"},
                ("vostok",),
            )

    def test_empty_day_contains_only_summary(self) -> None:
        result = DailyReportZipBuilder.build(date(2026, 9, 26), {"summary.pdf": b"%PDF-1.4"}, ())
        with ZipFile(io.BytesIO(result)) as archive:
            self.assertEqual(archive.namelist(), ["daily-report-2026-09-26/summary.pdf"])


class S3ExportSettingsTest(unittest.TestCase):
    def test_export_bucket_is_separate_and_retention_outlives_url(self) -> None:
        with self.assertRaises(ValueError):
            S3Config(bucket_exports="plans")
        with self.assertRaises(ValueError):
            S3Config(export_url_ttl_seconds=3600, export_retention_hours=1)


class S3ExportDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_export_bucket_configured_ttl_and_uploads_before_return(self) -> None:
        storage = Mock()
        storage.presigned_download_url = AsyncMock(return_value="https://example.invalid/file")
        storage.upload_file = AsyncMock()
        delivery = S3ExportDelivery(storage)
        now = datetime.now(UTC)
        result = await delivery.deliver(
            data=b"export",
            kind=ExportKind.DAILY_REPORT,
            planning_date=date(2026, 9, 26),
            filename="daily-report-2026-09-26.zip",
            content_type="application/zip",
        )
        bucket, key, ttl, filename, mime = storage.presigned_download_url.await_args.args
        self.assertEqual(bucket, cfg.s3.bucket_exports)
        self.assertEqual(ttl, cfg.s3.export_url_ttl_seconds)
        self.assertIn("/daily-report/2026-09-26/", key)
        self.assertTrue(key.endswith("/daily-report-2026-09-26.zip"))
        self.assertEqual((filename, mime), (result.filename, result.content_type))
        storage.upload_file.assert_awaited_once_with(bucket, key, b"export", "application/zip")
        self.assertEqual(result.size_bytes, 6)
        self.assertLessEqual(
            abs((result.expires_at - now).total_seconds() - cfg.s3.export_url_ttl_seconds), 2
        )

    async def test_size_limit_and_storage_failure_do_not_return_a_link(self) -> None:
        storage = Mock()
        storage.presigned_download_url = AsyncMock(return_value="https://example.invalid/file")
        storage.upload_file = AsyncMock()
        delivery = S3ExportDelivery(storage)
        params = dict(
            kind=ExportKind.PLAN,
            planning_date=date(2026, 9, 26),
            filename="plan-1.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        with patch.object(cfg.s3, "max_export_size_bytes", 1):
            with self.assertRaises(ExportTooLargeError):
                await delivery.deliver(data=b"too long", **params)
        storage.presigned_download_url.assert_not_awaited()
        storage.upload_file.assert_not_awaited()

        storage.presigned_download_url.side_effect = S3UnavailableError("presign")
        with self.assertRaises(S3UnavailableError):
            await delivery.deliver(data=b"x", **params)
        storage.upload_file.assert_not_awaited()

        storage.presigned_download_url.side_effect = None
        storage.upload_file.side_effect = S3UnavailableError("upload")
        with self.assertRaises(S3UnavailableError):
            await delivery.deliver(data=b"x", **params)


class S3ClientEndpointTest(unittest.TestCase):
    def test_presign_client_uses_public_endpoint(self) -> None:
        session = Mock()
        connection = S3Client(session)
        with (
            patch.object(cfg.s3, "endpoint_url", "http://minio:9000"),
            patch.object(cfg.s3, "public_endpoint_url", "https://downloads.example.invalid"),
        ):
            connection.get()
            self.assertEqual(session.client.call_args.kwargs["endpoint_url"], "http://minio:9000")
            client_config = session.client.call_args.kwargs["config"]
            self.assertEqual(client_config.connect_timeout, cfg.s3.connect_timeout_seconds)
            self.assertEqual(client_config.read_timeout, cfg.s3.read_timeout_seconds)
            connection.get(public=True)
            self.assertEqual(
                session.client.call_args.kwargs["endpoint_url"],
                "https://downloads.example.invalid",
            )


class S3PresignTest(unittest.IsolatedAsyncioTestCase):
    async def test_presign_uses_public_endpoint_and_download_headers(self) -> None:
        client = Mock()
        client.generate_presigned_url = AsyncMock(
            return_value="http://127.0.0.1:9000/exports/key?X-Amz-Signature=test"
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        connection = Mock()
        connection.get.return_value = context
        storage = S3Storage(connection)
        url = await storage.presigned_download_url(
            "exports", "key", 900, "report.zip", "application/zip"
        )
        self.assertIn("127.0.0.1", url)
        connection.get.assert_called_once_with(public=True)
        args = client.generate_presigned_url.await_args
        self.assertEqual(args.kwargs["ExpiresIn"], 900)
        self.assertEqual(
            args.kwargs["Params"]["ResponseContentDisposition"],
            'attachment; filename="report.zip"',
        )

    async def test_malformed_presigned_url_is_storage_failure(self) -> None:
        client = Mock()
        client.generate_presigned_url = AsyncMock(return_value=None)
        context = AsyncMock()
        context.__aenter__.return_value = client
        connection = Mock()
        connection.get.return_value = context
        with self.assertRaises(S3UnavailableError):
            await S3Storage(connection).presigned_download_url(
                "exports", "key", 900, "report.zip", "application/zip"
            )

    async def test_presign_sdk_failure_is_translated(self) -> None:
        client = Mock()
        client.generate_presigned_url = AsyncMock(
            side_effect=ClientError({"Error": {"Code": "500", "Message": "failed"}}, "GetObject")
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        connection = Mock()
        connection.get.return_value = context
        with self.assertRaises(S3UnavailableError):
            await S3Storage(connection).presigned_download_url(
                "exports", "key", 900, "report.zip", "application/zip"
            )


class DailyReportExportServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_passes_generated_zip_to_shared_delivery(self) -> None:
        planning_date = date(2026, 9, 26)
        reports = Mock()
        reports.build_snapshot = AsyncMock(
            return_value=SimpleNamespace(
                regions=(
                    SimpleNamespace(region=Region.VOSTOK),
                    SimpleNamespace(region=Region.YUGO_VOSTOK),
                )
            )
        )
        delivery = Mock()
        delivery.deliver = AsyncMock(
            return_value=ExportDownload(
                url="https://example.invalid/report",
                expires_at=datetime(2026, 9, 26, tzinfo=UTC) + timedelta(minutes=15),
                filename="daily-report-2026-09-26.zip",
                content_type="application/zip",
                size_bytes=100,
            )
        )
        with patch(
            "src.api.reports.service.DailyPdfRenderer.render",
            return_value={
                "summary.pdf": b"%PDF-1.4\nsummary",
                "vostok.pdf": b"%PDF-1.4\nfirst",
                "yugo_vostok.pdf": b"%PDF-1.4\nsecond",
            },
        ):
            result = await DailyReportExportService(reports, delivery).export(planning_date)
        self.assertEqual(result.url, "https://example.invalid/report")
        args = delivery.deliver.await_args.kwargs
        self.assertEqual(args["kind"], ExportKind.DAILY_REPORT)
        with ZipFile(io.BytesIO(args["data"])) as archive:
            self.assertEqual(len(archive.namelist()), 3)
        reports.build_snapshot.assert_awaited_once_with(planning_date)

    async def test_storage_failure_maps_to_api_error(self) -> None:
        reports = Mock()
        reports.build_snapshot = AsyncMock(return_value=SimpleNamespace(regions=()))
        delivery = Mock()
        delivery.deliver = AsyncMock(side_effect=S3UnavailableError("unavailable"))
        with patch(
            "src.api.reports.service.DailyPdfRenderer.render",
            return_value={"summary.pdf": b"%PDF-1.4\nsummary"},
        ):
            with self.assertRaises(DailyReportStorageError):
                await DailyReportExportService(reports, delivery).export(date(2026, 9, 26))

    async def test_invalid_report_does_not_upload(self) -> None:
        reports = Mock()
        reports.build_snapshot = AsyncMock(
            return_value=SimpleNamespace(regions=(SimpleNamespace(region=Region.VOSTOK),))
        )
        delivery = Mock()
        delivery.deliver = AsyncMock()
        with patch(
            "src.api.reports.service.DailyPdfRenderer.render",
            return_value={"summary.pdf": b"%PDF-1.4\nsummary"},
        ):
            with self.assertRaises(DailyReportGenerationError):
                await DailyReportExportService(reports, delivery).export(date(2026, 9, 26))
        delivery.deliver.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
