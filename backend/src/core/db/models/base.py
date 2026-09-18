from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import as_declarative, declared_attr


@as_declarative()
class Base:
    @declared_attr.directive
    def __tablename__(cls: type) -> str:
        return cls.__name__.lower()

    def to_dict(self) -> dict[str, object]:
        """
        Преобразует объект модели в словарь по колонкам.
        """
        mapper = inspect(self.__class__)
        columns = getattr(mapper, "columns", None)
        if columns is None:
            return {}

        data: dict[str, object] = {}
        for col in columns:
            data[col.key] = getattr(self, col.key)
        return data

    def update(self: Base, **kwargs: object) -> Base:
        """
        Обновляет атрибуты объекта.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self

    @classmethod
    def from_dict(cls: type[Base], data: dict[str, object]) -> Base:
        """
        Создаёт экземпляр из словаря (без **kwargs, чтобы IDE не бузила).
        Фильтруем только реальные колонки.
        """
        mapper = inspect(cls)
        columns = getattr(mapper, "columns", None)
        allowed = {c.key for c in columns} if columns is not None else set()

        obj = cls()
        for k, v in data.items():
            if k in allowed:
                setattr(obj, k, v)
        return obj
