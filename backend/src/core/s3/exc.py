class S3UnavailableError(Exception):
    """S3-совместимое хранилище не выполнило операцию."""


class ExportTooLargeError(Exception):
    """Размер экспорта превышает настроенный предел."""
