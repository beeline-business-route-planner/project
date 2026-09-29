"""Typed scenario catalog used by collection and the generated test matrix."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    id: str
    node: str
    title: str
    layer: str
    domain: str
    status: str


def load_scenarios(path: Path) -> dict[str, Scenario]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported scenario catalog version")
    scenarios: dict[str, Scenario] = {}
    ids: set[str] = set()
    for raw in document.get("scenario", []):
        scenario = Scenario(**raw)
        if scenario.node in scenarios or scenario.id in ids:
            raise ValueError(f"Duplicate scenario node or ID: {scenario.node}")
        if scenario.layer not in {"unit", "integration", "e2e"}:
            raise ValueError(f"Invalid layer for {scenario.id}: {scenario.layer}")
        if scenario.status != "active":
            raise ValueError(f"Unsupported status for {scenario.id}: {scenario.status}")
        if not scenario.node.startswith(f"tests/{scenario.layer}/{scenario.domain}/"):
            raise ValueError(f"Scenario {scenario.id} is outside its layer/domain")
        scenarios[scenario.node] = scenario
        ids.add(scenario.id)
    return scenarios
