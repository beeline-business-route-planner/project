from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Когда появится первая модель и её репозиторий, подключай их сюда явно, например:
        # self.users = UserRepository(self.session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
