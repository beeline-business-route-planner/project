from datetime import time
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

BASE_DIR = Path(__file__).parent.parent.parent
TOML_SETTINGS_PATH = BASE_DIR / "config.toml"

SETTINGS_SOURCES: tuple[tuple[Path, type[PydanticBaseSettingsSource]], ...] = (
    (TOML_SETTINGS_PATH, TomlConfigSettingsSource),
)


class CorsConfig(BaseModel):
    origins: list[str] = Field(default_factory=list)


class DatabaseConfig(BaseModel):
    postgres_username: str = ""
    postgres_db: str = ""
    postgres_port: int = 5432
    postgres_host: str = ""
    postgres_password: str = ""

    alembic_postgres_host: str | None = None

    @property
    def async_database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_username}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def alembic_url(self) -> str:
        host = self.alembic_postgres_host or self.postgres_host
        return f"postgresql+asyncpg://{self.postgres_username}:{self.postgres_password}@{host}:{self.postgres_port}/{self.postgres_db}"


class S3Config(BaseModel):
    endpoint_url: str = ""
    public_endpoint_url: str | None = None
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=60, gt=0)
    bucket_answers: str = "answers"
    bucket_uploads: str = "uploads"
    bucket_plans: str = "plans"
    bucket_exports: str = "exports"
    export_prefix: str = Field(default="exports", pattern=r"^[A-Za-z0-9][A-Za-z0-9/_-]*$")
    export_url_ttl_seconds: int = Field(default=900, gt=0)
    export_retention_hours: int = Field(default=24, gt=0)
    max_export_size_bytes: int = Field(default=10_000_000, gt=0)

    @model_validator(mode="after")
    def validate_export_settings(self) -> Self:
        if self.bucket_exports in {
            self.bucket_answers,
            self.bucket_uploads,
            self.bucket_plans,
        }:
            raise ValueError("Бакет экспортов должен отличаться от остальных бакетов S3")
        if self.export_url_ttl_seconds >= self.export_retention_hours * 3600:
            raise ValueError("Срок хранения экспорта должен превышать время жизни ссылки")
        return self


class GeocodingConfig(BaseModel):
    base_url: str = "https://suggestions.dadata.ru"
    api_key: str = ""
    timeout_seconds: float = 10.0
    max_concurrent_requests: int = Field(default=10, gt=0)
    max_qc_geo: int = Field(default=1, ge=0, le=5)
    suggestions_count: int = Field(default=5, ge=1, le=20)


class RoutingConfig(BaseModel):
    """OSRM Table API: отдельный сервер на профиль, пробки не учитываются."""

    car_table_url: str = "https://router.project-osrm.org/table/v1/driving"
    foot_table_url: str = "https://routing.openstreetmap.de/routed-foot/table/v1/driving"
    bike_table_url: str = "https://routing.openstreetmap.de/routed-bike/table/v1/driving"
    user_agent: str = "beeline-business-route-planner/0.1"
    timeout_seconds: float = 60.0
    travel_buffer_multiplier: float = 1.10
    # Измеренный лимит публичных серверов OSRM: 100 точек — "200 OK", 101 — "400 TooBig".
    max_table_coordinates: int = 100
    public_transport_speed_kmh: float = Field(default=20.0, gt=0)
    public_transport_wait_minutes: int = Field(default=10, ge=0)


class TravelMatrixConfig(BaseModel):
    """Провайдер матриц времени и расстояния для алгоритма."""

    provider: Literal["osrm", "dgis"] = "osrm"


class DgisConfig(BaseModel):
    base_url: str = "https://routing.api.2gis.com"
    api_key: str = ""
    api_version: str = "2.0"
    timeout_seconds: float = 60.0
    max_matrix_sources: int = 10
    max_matrix_targets: int = 10
    rate_limit_retries: int = Field(default=4, ge=0)
    rate_limit_backoff_seconds: float = Field(default=2.0, gt=0)
    public_transport_types: list[str] = Field(
        default_factory=lambda: [
            "bus",
            "trolleybus",
            "tram",
            "metro",
            "shuttle_bus",
            "suburban_train",
        ]
    )


class PlanningConfig(BaseModel):
    max_file_size_bytes: int = 10_000_000
    default_shift_start: time = time(hour=10)
    default_shift_end: time = time(hour=22)
    default_vehicle_type: str = "public_transport"
    approval_ttl_minutes: int = 10


class AlgorithmConfig(BaseModel):
    emergency_response_minutes: int = 120
    priority_tier_weight: int = 1000
    route_candidates_per_engineer: int = 48
    route_candidate_improvement_rounds: int = 2
    route_candidates_per_improvement_round: int = 4
    selection_node_budget: int = 5000
    lns_iterations: int = 95
    lns_random_seed: int = 20260925
    lns_min_removal_fraction: float = 0.08
    lns_max_removal_fraction: float = 0.3
    lns_insertion_noise: float = 0.15
    lns_acceptance_threshold: float = 0.02
    lns_new_route_penalty_minutes: int = 10_000
    lns_balance_load_weight: float = 0.5
    emergency_phase_state_budget: int = 50_000


class LoggingConfig(BaseModel):
    level: str = "INFO"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        toml_file=TOML_SETTINGS_PATH,
        env_nested_delimiter="__",
    )

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    s3: S3Config = Field(default_factory=S3Config)
    geocoding: GeocodingConfig = Field(default_factory=GeocodingConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    travel_matrix: TravelMatrixConfig = Field(default_factory=TravelMatrixConfig)
    dgis: DgisConfig = Field(default_factory=DgisConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    algorithm: AlgorithmConfig = Field(default_factory=AlgorithmConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cors: CorsConfig = Field(default_factory=CorsConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        active_sources = [
            method(settings_cls) for path, method in SETTINGS_SOURCES if path.exists()
        ]
        return EnvSettingsSource(settings_cls), *active_sources


cfg = Config()
