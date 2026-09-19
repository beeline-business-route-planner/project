import pytest

from beeline_backend.domain.errors import DomainError
from beeline_backend.infrastructure.importer import XlsxDatasetImporter


def test_importer_rejects_control_file(synthetic_xlsx: bytes) -> None:
    importer = XlsxDatasetImporter()
    with pytest.raises(DomainError) as exc_info:
        importer.parse("Восток Контрольное распределение..xlsx", synthetic_xlsx)
    assert exc_info.value.code == "unsupported_dataset_file"


def test_repeated_address_keeps_distinct_requests(synthetic_xlsx: bytes) -> None:
    imported = XlsxDatasetImporter().parse("Восток Синтетические данные.xlsx", synthetic_xlsx)
    assert len(imported.requests) == 2
    assert {item.external_id for item in imported.requests} == {"1001", "1002"}
    assert imported.requests[0].address == imported.requests[1].address


def test_unknown_bk_hd_requires_mapping(synthetic_xlsx: bytes) -> None:
    imported = XlsxDatasetImporter().parse("Восток Синтетические данные.xlsx", synthetic_xlsx)
    assert all(item.mapping_state == "mapped" for item in imported.requests)

