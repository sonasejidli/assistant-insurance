"""Editable insurance concepts and context-dependent query mappings."""

import json
import re
from pathlib import Path

from App.azerbaijani import LEMMATIZER, ascii_key, surface_tokens

DICTIONARY_PATH = Path(__file__).parent / "config" / "insurance-terminology.json"
CONTEXT_BREAK = re.compile(r"[!?;\n]+|(?<!\d)\.|\.(?!\d)")


def normalized_phrase(text: str) -> str:
    return " ".join(ascii_key(LEMMATIZER.lemmatize(word)) for word in surface_tokens(text))


def phrase_pattern(phrases: list[str]) -> re.Pattern:
    variants = {normalized_phrase(phrase) for phrase in phrases}
    if not variants or "" in variants:
        raise ValueError("Terminology phrases must contain words")
    alternatives = sorted(variants, key=lambda phrase: (-len(phrase), phrase))
    return re.compile(r"\b(?:" + "|".join(map(re.escape, alternatives)) + r")\b")


class InsuranceTerminology:
    def __init__(self, path: Path = DICTIONARY_PATH):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.expansion_enabled = data.get("expansion_enabled", True)
        self.aliases = {key: value["aliases"] for key, value in data["concepts"].items()}
        self.evidence_concepts = {key for key, value in data["concepts"].items()
                                  if value.get("evidence", not value.get("role", False))}
        self.patterns = {key: phrase_pattern(aliases) for key, aliases in self.aliases.items()}
        self.rules = []
        for rule in data["expressions"]:
            candidates = rule["candidates"]
            if not candidates or not candidates.keys() <= self.aliases.keys():
                raise ValueError(f"Unknown or missing terminology candidates for {rule['phrases']}")
            if len(candidates) > 1 and any(not cues for cues in candidates.values()):
                raise ValueError(f"Ambiguous terminology requires contextual cues for {rule['phrases']}")
            self.rules.append((
                phrase_pattern(rule["phrases"]),
                {key: phrase_pattern(cues) if cues else None for key, cues in candidates.items()},
                rule.get("expand_when_unclear", False),
            ))
        self.related = []
        for rule in data.get("related_searches", []):
            concepts = set(rule["concepts"])
            alternatives = tuple(rule.get("alternatives", []))
            if not rule["requires"] or not (concepts | set(alternatives)) <= self.aliases.keys():
                raise ValueError(f"Invalid related search: {rule}")
            self.related.append((tuple(phrase_pattern(group) for group in rule["requires"]), concepts, alternatives))

    def direct_concepts(self, text: str) -> set[str]:
        matches = []
        for segment in CONTEXT_BREAK.split(text):
            phrase = normalized_phrase(segment)
            spans = [(match.start(), match.end(), key) for key, pattern in self.patterns.items()
                     for match in pattern.finditer(phrase)]
            matches.extend(key for start, end, key in spans if not any(
                other_start <= start and end <= other_end and (other_start, other_end) != (start, end)
                for other_start, other_end, _ in spans
            ))
        return set(matches)

    def query_concepts(self, text: str) -> set[str]:
        return self.expand(text)[0]

    def expand(self, text: str) -> tuple[set[str], list[tuple[str, ...]]]:
        """Return supported search concepts and separate groups of plausible alternatives."""
        concepts = self.direct_concepts(text)
        alternatives = []
        if not self.expansion_enabled:
            return concepts, alternatives
        for segment in CONTEXT_BREAK.split(text):
            phrase = normalized_phrase(segment)
            for expression, candidates, expand_when_unclear in self.rules:
                if expression.search(phrase):
                    matches = [key for key, cue in candidates.items() if cue is None or cue.search(phrase)]
                    if len(matches) == 1:
                        concepts.add(matches[0])
                    elif expand_when_unclear:
                        alternatives.append(tuple(matches or candidates))
            for required, related, plausible in self.related:
                if all(pattern.search(phrase) for pattern in required):
                    concepts.update(related)
                    if plausible:
                        alternatives.append(plausible)
        return concepts, list(dict.fromkeys(alternatives))


TERMINOLOGY = InsuranceTerminology()
