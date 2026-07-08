"""requirements.txt must cover every pyproject dependency (name-level).

Railway's builder installs from requirements.txt for a nested Root Directory
service, so a dep added only to pyproject.toml exists locally but not in prod —
the failure mode behind the 2026-07-08 /kg outage (neo4j missing, every graph
touch degrading on ModuleNotFoundError). See
docs/solutions/integration-issues/requirements-txt-drift-and-deferred-prod-wiring.md.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def _name(spec: str) -> str:
    return re.split(r"[\[<>=~!]", spec)[0].strip().lower()


def test_requirements_covers_pyproject_deps():
    deps = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    wanted = {_name(d) for d in deps}
    have = {
        _name(line)
        for line in (API_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert wanted <= have, f"missing from requirements.txt: {sorted(wanted - have)}"
