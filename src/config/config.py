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


class Logging(BaseModel):
    level: str = "INFO"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        toml_file=TOML_SETTINGS_PATH,
        env_nested_delimiter="__",
    )

    database: Database = Database()
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
