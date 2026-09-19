from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://beeline:beeline@localhost:55432/beeline"
    business_timezone: str = "Europe/Moscow"
    geocoder_mode: Literal["missing", "dgis", "nominatim", "hybrid", "demo"] = "missing"
    routing_provider: Literal["osrm", "hybrid", "dgis", "demo", "yandex"] = "osrm"
    planner_provider: str = "deterministic"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "beeline-business-planner/1.0"
    nominatim_email: str | None = None
    nominatim_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    nominatim_min_interval_seconds: float = Field(default=1.05, ge=1.0, le=60)
    osrm_base_url: str = "http://localhost:5000"
    osrm_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    osrm_max_coordinates: int = Field(default=80, ge=2, le=500)
    osrm_max_concurrency: int = Field(default=8, ge=1, le=32)
    osrm_graph_manifest: Path | None = None
    osrm_graph_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    redis_url: str | None = None
    redis_route_ttl_seconds: int = Field(default=21600, ge=1, le=604800)
    redis_timeout_seconds: float = Field(default=0.25, gt=0, le=2)
    route_overview_tolerance_meters: float = Field(default=20, ge=0, le=100)
    dgis_base_url: str = "https://routing.api.2gis.com"
    dgis_catalog_base_url: str = "https://catalog.api.2gis.com"
    dgis_api_key: str | None = None
    dgis_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    dgis_matrix_block_size: int = Field(default=25, ge=1, le=25)
    hybrid_dgis_max_route_points: int = Field(default=5, ge=2, le=10)
    yandex_api_key: str | None = None
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    cors_allow_credentials: bool = False
    cors_allow_methods: Annotated[list[str], NoDecode] = ["GET", "POST", "PATCH", "OPTIONS"]
    cors_allow_headers: Annotated[list[str], NoDecode] = [
        "Content-Type",
        "Idempotency-Key",
        "X-Correlation-ID",
    ]
    cors_expose_headers: Annotated[list[str], NoDecode] = [
        "X-Correlation-ID",
        "Content-Disposition",
    ]
    cors_max_age: int = Field(default=600, ge=0, le=86400)
    log_level: str = "INFO"

    @field_validator(
        "cors_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "cors_expose_headers",
        mode="before",
    )
    @classmethod
    def split_list_setting(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                parsed = json.loads(value)
                if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                    raise ValueError("CORS list settings must contain strings")
                return parsed
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
