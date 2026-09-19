from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class ConflictError(DomainError):
    pass


class DependencyUnavailableError(DomainError):
    pass


class NotFoundError(DomainError):
    pass

