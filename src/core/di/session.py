from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.core.db.db import Session, engine
from src.core.db.uow import UnitOfWork


class DbProvider(Provider):
    @provide(scope=Scope.APP)
    def get_engine(self) -> AsyncEngine:
        return engine

    @provide(scope=Scope.APP)
    def get_sessionmaker(self) -> async_sessionmaker:
        return Session

    @provide(scope=Scope.REQUEST)
    async def get_session(self, session_factory: async_sessionmaker) -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    async def get_uow(self, session: AsyncSession) -> AsyncIterator[UnitOfWork]:
        uow = UnitOfWork(session)
        try:
            yield uow
        except Exception:
            await uow.rollback()
            raise
