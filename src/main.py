import logging
from contextlib import asynccontextmanager

import uvicorn
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka as setup_fastapi_dishka
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from src.api import router
from src.config import cfg
from src.core.di import DbProvider
from src.core.logging import setup_logging
from src.core.metrics import PrometheusMiddleware, http_requests_total
from src.core.middleware import RequestLoggingMiddleware

log = logging.getLogger(__name__)

container = make_async_container(
    DbProvider(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(cfg.logging.level)
    try:
        yield
    finally:
        await container.close()


app = FastAPI(
    title="__PROJECT_TITLE__",
    lifespan=lifespan,
)

setup_fastapi_dishka(app=app, container=container)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors.origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("Unhandled exception", exc_info=exc)
    http_requests_total.labels(method=request.method, path=request.url.path, status=500).inc()
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
async def ping() -> dict[str, str]:
    return {"ping": "pong"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def main() -> None:
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, log_config=None, workers=2)


if __name__ == "__main__":
    main()
