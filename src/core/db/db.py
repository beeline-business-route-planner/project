from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import cfg

engine = create_async_engine(
    cfg.database.async_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)

Session = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
