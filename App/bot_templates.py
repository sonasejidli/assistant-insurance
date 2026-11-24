from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent / "config" / "bot-templates.json"


@lru_cache(maxsize=1)
def load_templates() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def normalize_language(lang: str | None) -> str:
    if lang in ("az", "ru", "en"):
        return lang
    return "az"


def get_language_block(lang: str | None) -> dict[str, Any]:
    templates = load_templates()
    normalized = normalize_language(lang)
    if normalized in templates:
        return templates[normalized]
    return templates["az"]


def get_examples(lang: str | None) -> list[dict[str, str]]:
    return list(get_language_block(lang).get("examples") or [])


def get_opening(lang: str | None) -> dict[str, str]:
    return dict(get_language_block(lang).get("opening") or {})


def get_disclaimer_footer(lang: str | None) -> str:
    return str(get_language_block(lang).get("disclaimer_footer") or "")


def get_clarification(lang: str | None) -> str:
    return str(get_language_block(lang).get("clarification") or "")


def get_intent_template(lang: str | None, intent: str) -> str:
    intents = get_language_block(lang).get("intents") or {}
    value = intents.get(intent)
    return str(value or "")
