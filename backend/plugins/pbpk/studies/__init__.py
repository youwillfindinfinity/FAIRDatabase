"""Bundled FAIR PBPK study models.

Each entry maps a URL slug to the import path of a study subpackage exposing
``execute(params) -> dict`` and optional ``SCENARIOS`` / ``COMPOUNDS`` /
``DEFAULT_PARAMS`` module-level constants.

Runners are imported lazily on first use because they pull in heavy optional
deps (``libsbml``, ``scipy``). Plugin discovery must not require them.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import TypedDict


class StudyMeta(TypedDict):
    slug: str
    label: str
    template: str
    module: str
    has_scenarios: bool
    has_compounds: bool


STUDIES: dict[str, StudyMeta] = {
    "ratier": {
        "slug": "ratier",
        "label": "Ratier 2024 — lifetime PFAS PBPK",
        "template": "pbpk/studies/ratier.html",
        "module": "plugins.pbpk.studies.ratier.runner",
        "has_scenarios": True,
        "has_compounds": False,
    },
    "rovira": {
        "slug": "rovira",
        "label": "Rovira 2019 — PFAS PBPK",
        "template": "pbpk/studies/rovira.html",
        "module": "plugins.pbpk.studies.rovira.runner",
        "has_scenarios": False,
        "has_compounds": True,
    },
    "verner": {
        "slug": "verner",
        "label": "Ouidir 2025 (Verner) — PFAS PBPK",
        "template": "pbpk/studies/verner.html",
        "module": "plugins.pbpk.studies.verner.runner",
        "has_scenarios": False,
        "has_compounds": True,
    },
    "generic": {
        "slug": "generic",
        "label": "Generic PFAS PBPK",
        "template": "pbpk/studies/generic.html",
        "module": "plugins.pbpk.studies.generic.runner",
        "has_scenarios": True,
        "has_compounds": True,
    },
}


def load(slug: str) -> ModuleType:
    meta = STUDIES.get(slug)
    if meta is None:
        raise KeyError(slug)
    return importlib.import_module(meta["module"])
