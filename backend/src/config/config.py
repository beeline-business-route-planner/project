from datetime import time
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

BASE_DIR = Path(__file__).parent.parent.parent
TOML_SETTINGS_PATH = BASE_DIR / "config.toml"

PathsSources: list[tuple[Path, type[PydanticBaseSettingsSource]]] = [
    (TOML_SETTINGS_PATH, TomlConfigSettingsSource),
]


class CORS(BaseModel):
    origins: list[str] = []


class Database(BaseModel):
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


class S3(BaseModel):
    endpoint_url: str = ""
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"
    bucket_answers: str = "answers"
    bucket_uploads: str = "uploads"
    bucket_plans: str = "plans"


class Geocoding(BaseModel):
    base_url: str = "https://nominatim.openstreetmap.org"
    user_agent: str = (
        "beeline-business-route-planner/0.1 "
        "(+https://github.com/beeline-business-route-planner/project)"
    )
    timeout_seconds: float = 15.0
    min_request_interval_seconds: float = 1.0
    country_codes: str = "ru"


class Routing(BaseModel):
    base_url: str = "https://router.project-osrm.org"
    profile: str = "driving"
    timeout_seconds: float = 60.0
    travel_buffer_multiplier: float = 1.10
    # Измеренный лимит публичного demo-сервера (router.project-osrm.org):
    # 100 точек - "200 OK", 101 - "400 TooBig". Самостоятельный инстанс
    # (см. docs/ROUTING.md) обычно без этого лимита — значение тогда можно
    # поднять через конфиг, не трогая код.
    max_table_coordinates: int = 100


class Planning(BaseModel):
    max_file_size_bytes: int = 10_000_000
    default_shift_start: time = time(hour=9)
    default_shift_end: time = time(hour=21)
    default_vehicle_type: str = "public_transport"


class Logging(BaseModel):
    level: str = "INFO"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        toml_file=TOML_SETTINGS_PATH,
        env_nested_delimiter="__",
    )

    database: Database = Database()
    s3: S3 = S3()
    geocoding: Geocoding = Geocoding()
    routing: Routing = Routing()
    planning: Planning = Planning()
    logging: Logging = Logging()
    cors: CORS = CORS()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        active_sources = [method(settings_cls) for path, method in PathsSources if path.exists()]
        return EnvSettingsSource(settings_cls), *active_sources


cfg = Config()
