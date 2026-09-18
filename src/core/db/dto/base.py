import dataclasses
from dataclasses import dataclass
from typing import Any, Self


@dataclass
class BaseDTO:
    @classmethod
    def from_orm(cls, obj: Any) -> Self:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{f: getattr(obj, f) for f in fields})
