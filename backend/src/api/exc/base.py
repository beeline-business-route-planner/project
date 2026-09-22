from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

REGISTRY: list[tuple[type[Exception], int, str, dict[str, str] | None]] = []


def http_error(status_code: int, detail: str, headers: dict[str, str] | None = None):
    """Декоратор на исключение, которым домен владеет сам — говорит, в какой
    HTTP-ответ его перевести. Живёт и применяется прямо в `exc/<domain>.py`
    (там же, где определён сам класс исключения) — единственный слой
    исключений на домен, никакого параллельного `service_exc.py` нет.

    Исключения ЧУЖИХ core-сервисов (`src/core/<system>/`, например
    `AddressNotFoundError` из `geocoding`) сюда не попадают напрямую — у
    них нет одной "правильной" интерпретации на все домены сразу (другой
    домен, например будущий `ReplanningService`, может захотеть другой
    статус/текст на ту же ошибку геокодера). Поэтому домен, вызывающий
    чужой core-сервис, сам ловит его исключение в своём `service.py` и
    перевыбрасывает **свой** задекорированный эквивалент — тот уже ничем
    не отличается от "своего" исключения, оба идут через этот же декоратор
    (см. `src/api/planning/service.py`, `src/api/exc/planning.py`).
    """

    def decorator(exc_type: type[Exception]) -> type[Exception]:
        REGISTRY.append((exc_type, status_code, detail, headers))
        return exc_type

    return decorator


def register_all(app: FastAPI) -> None:
    """Регистрирует всё, что накопилось в `REGISTRY` через `@http_error` на
    момент вызова — вызывается один раз при старте (`main.py`), после того
    как импорт роутеров уже подтянул все `exc/<domain>.py` (декораторы
    успели отработать на уровне импорта модуля)."""
    for exc_type, status_code, detail, headers in REGISTRY:
        add_handler(app, exc_type, status_code, detail, headers)


def add_handler(
    app: FastAPI,
    exc_type: type[Exception],
    status_code: int,
    detail: str,
    headers: dict[str, str] | None,
) -> None:
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)

    app.add_exception_handler(exc_type, handler)
