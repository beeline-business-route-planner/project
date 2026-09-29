"""Render the reviewable scenario matrix from its checked catalog."""

import argparse
from pathlib import Path

from tests.support.scenarios import load_scenarios


def render() -> str:
    root = Path(__file__).resolve().parents[1]
    scenarios = load_scenarios(root / "scenarios.toml")
    lines = [
        "# Матрица тестовых сценариев",
        "",
        "Генерируется из `tests/scenarios.toml`; вручную не редактировать.",
        "",
        "| ID | Слой | Домен | Сценарий | Тест |",
        "|---|---|---|---|---|",
    ]
    for scenario in scenarios.values():
        lines.append(
            f"| `{scenario.id}` | {scenario.layer} | {scenario.domain} | "
            f"{scenario.title.replace('|', '&#124;')} | `{scenario.node}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "TEST_MATRIX.md"
    expected = render()
    if options.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit("TEST_MATRIX.md устарела: запустите make test-matrix-update")
    else:
        output.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
