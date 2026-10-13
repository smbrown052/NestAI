"""Reuse the audited legacy parsers/scorer without importing the UI runtime."""

import importlib.util
import json
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
        parsed = _load("apartments", ROOT / "parser/apartment_listing.py").parse_apartment_listing(text)
        for unit in parsed.get("units", []):
            unit["id"] = unit["unit_label"]
        return parsed
    result = _load("homes", ROOT / "parser/home_listing.py").parse_home_listing_text(text)
    from dataclasses import asdict
    return asdict(result)


def rank(rows: list[dict], priorities: dict[str, float]) -> list[dict]:
    if not rows:
        return []
    import pandas as pd
    scorer = _load("scorer", ROOT / "lifestyle_scoring.py").LifestyleScorer(priorities or None)
    frame = scorer.score_apartments(pd.DataFrame(rows))
    return json.loads(frame.to_json(orient="records"))
