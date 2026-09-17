"""Put the documentation inside the wheel, so `gflow docs` can read it (#861).

``docs/`` is not a Python package and must not become one, but the pages have to travel
with the distribution: the user in #861 is an agent that ran ``uv tool install gflow-cli``
and has no checkout to fall back on. A command that can only print GitHub URLs to that
user does not solve the problem it was filed for.

**Why a hook and not two lines of config.** The obvious form is
``force-include = { "docs" = "gflow_cli/_docs" }`` plus ``exclude`` for the parts that
should not ship. That was built and inspected on 2026-09-17, and **hatchling's exclude
patterns do not apply to forced inclusions**: 145 files under ``docs/superpowers/`` and 3
under ``docs/assets/`` landed in the wheel anyway, 4.3 MB of them. The alternative --
listing 126 pages by hand in ``pyproject.toml`` -- drifts the first time someone adds one.

A glob resolved at build time is the only shape that ships exactly the top-level pages and
cannot go stale, because the glob IS the list. Measurement:
``docs/superpowers/plans/2026-09-17-gflow-docs-command/SCENARIO.md`` § M1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: Where the pages land inside the installed package. `gflow_cli.docs_catalog` reads this
#: name through `importlib.resources`; the two must agree.
DOCS_PACKAGE_DIR = "gflow_cli/_docs"


class DocsBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    """Force-include every top-level ``docs/*.md`` as package data."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        # Non-recursive on purpose: `docs/assets/` is 2 MB of images and
        # `docs/superpowers/` is plans and spikes. Neither is a page the command lists,
        # and shipping them was measured at 4.3 MB for no reader.
        for page in sorted(Path(self.root, "docs").glob("*.md")):
            build_data["force_include"][str(page)] = f"{DOCS_PACKAGE_DIR}/{page.name}"
