"""Reuse the audited legacy parsers/scorer without importing the UI runtime."""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "legacy" / "streamlit"


def _load(name: str, path: Path):
    module_name = f"_nestai_shared_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def parse_listing(text: str, kind: str) -> dict:
    if kind == "apartment":
        parsed = _load("apartment_text", ROOT / "text_parser.py").parse_apartment_text(text)
        for unit in parsed.get("units", []):
            unit["id"] = unit.get("unit", unit.get("unit_label"))
        return parsed
    result = _load("homes", ROOT / "parser/home_listing.py").parse_home_listing_text(text)
    from dataclasses import asdict
    return asdict(result)


def rank(rows: list[dict], priorities: dict[str, float] | None = None,
         constraints: dict | None = None, profile: dict | None = None) -> list[dict]:
    from shared.decision import rank_rows
    return rank_rows(rows, priorities or None, constraints, profile)
