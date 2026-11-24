"""Resolve referential insurance questions using one grounded prior turn."""

import re
from dataclasses import dataclass, field

from App.bot_templates import get_clarification
from App.intent import SOCIAL_INTENTS, classify_intent_rule
from App.insurance_terminology import TERMINOLOGY
from App.azerbaijani import ascii_key, normalize_az


FOLLOW_UP = re.compile(
    r"^(?:bəs\b|digər\s+hallarda\b|bu\s+(?:hal\w*|barədə|müddət\w*|qayda\w*|şərt\w*|istisna\w*|məbləğ\w*)\b|"
    r"bu nə\b|həmin\s+(?:hal\w*|vəziyyət\w*)\b|(?:what|how) about\b|and\b|also\b|(?:does|is|are|can) (?:it|this|that)\b|"
    r"(?:what|how (?:long|much)) (?:is|are|does) (?:it|this|that|they|these|those)\b|"
    r"а (?:что|как|если)\b|(?:это|этот|эта|этого)\b)", re.IGNORECASE,
)
AZ_QUESTION_WORD = re.compile(r"\b(?:hansı|necə|neçə|nə vaxt|nə zaman|nə qədər|nədir|nə|kim|niyə)\b", re.IGNORECASE)
PRODUCT = re.compile(r"\b(?:kasko\w*|icbari\s+sığorta\w*|tibbi\s+sığorta\w*|"
                     r"aqrar\s+sığorta\w*|təkrarsığorta\w*|iş\s+qəza\w*|motor insurance|medical insurance|health insurance|каско)\b",
                     re.IGNORECASE)
INSURANCE_ANCHOR = re.compile(r"\b(?:sığorta\w*|sigorta\w*|kasko\w*|insurance|страхован\w*|каско|"
                              r"(?:maddə|article|статья)\s+\d+(?:[.-]\d+)*)\b", re.IGNORECASE)
BARE_CASE = re.compile(r"^(?:bəs\s+)?(?:bu|həmin)\s+(?:halda|vəziyyətdə)$", re.IGNORECASE)
ALTERNATIVES = re.compile(r"\b(?:və ya|yaxud|or|или)\b|\?", re.IGNORECASE)
FOLLOW_UP_ALIASES = {ascii_key(text): text for text in (
    "bəs bu halda", "bəs istisnalar necə", "bu müddət nə qədərdir", "digər hallarda necə olur", "bəs sağlamlıq məlumatları",
)}
ELLIPTICAL_INSURANCE_FOLLOW_UP = re.compile(
    r"(?:istisnalar\s+(?:hansılardır|nələrdir|nədir)|hansı\s+(?:istisnalar\s+var|sənədlər\s+(?:lazımdır|tələb olunur))|"
    r"what are the (?:exceptions|exclusions)|what (?:documents|paperwork) (?:are|is) (?:required|needed)|"
    r"which (?:exceptions|exclusions) apply|which documents are (?:required|needed)|"
    r"какие (?:есть )?исключения|какие документы (?:нужны|требуются))",
    re.IGNORECASE,
)


def follow_up_text(text: str) -> str:
    current = " ".join(text.split()).strip(" ?.!")
    return FOLLOW_UP_ALIASES.get(ascii_key(normalize_az(current)), current)


def is_follow_up(text: str) -> bool:
    current = follow_up_text(text)
    return bool(FOLLOW_UP.match(current) or ELLIPTICAL_INSURANCE_FOLLOW_UP.fullmatch(current))


@dataclass(frozen=True)
class QueryResolution:
    original: str
    standalone: str | None
    context: tuple[str, ...] = ()
    history: tuple[str, ...] = field(default=(), compare=False)
    dense_hypothesis: str | None = None

    @property
    def normalized(self) -> str | None:
        return normalize_az(self.standalone) if self.standalone else None

    @property
    def dense_query(self) -> str | None:
        return self.dense_hypothesis or self.standalone

    @property
    def bm25_query(self) -> str | None:
        return self.standalone

    @property
    def rerank_query(self) -> str | None:
        return self.standalone


def _prior_anchor(history: list[str]) -> str | None:
    for previous in reversed(history):
        if classify_intent_rule(previous) in SOCIAL_INTENTS:
            continue
        if ELLIPTICAL_INSURANCE_FOLLOW_UP.fullmatch(follow_up_text(previous)):
            continue
        if not is_follow_up(previous) and (
            INSURANCE_ANCHOR.search(previous) or TERMINOLOGY.query_concepts(previous) & TERMINOLOGY.evidence_concepts
        ):
            return previous
        # A substantive intervening turn may have changed the topic or the referent.
        return None
    return None


def _azerbaijani_question(current: str, prior: str) -> str | None:
    current = re.sub(r"^bəs\s*[,–—-]?\s*", "", current, flags=re.IGNORECASE)
    heading = AZ_QUESTION_WORD.split(prior.rstrip("?.!"), maxsplit=1)[0].strip(" ,")
    if not heading or len(heading.split()) < 2:
        return None
    if BARE_CASE.fullmatch(current):
        if (ALTERNATIVES.search(prior.rstrip("? ")) or
                not re.search(r"\b(?:hal\w*|şərt\w*|əgər|olduqda|olarsa|vursam|baş verdikdə)\b",
                              prior, re.IGNORECASE)):
            return None
        if "ödəniş" not in heading.lower() and re.search(r"\bödəniş\w*\b", prior, re.IGNORECASE):
            heading += " sığorta ödənişi"
        return f"{heading} üçün hansı şərtlər tətbiq olunur?"
    if re.fullmatch(r"(?:bu\s+)?istisnalar(?:\s+(?:necə|nədir|hansılardır))?", current, re.IGNORECASE):
        return f"{heading} ilə bağlı hansı istisnalar var?"
    if re.fullmatch(r"digər hallarda necə olur", current, re.IGNORECASE):
        return f"{heading} digər hallarda hansı qaydalara tabedir?" if re.search(r"\bhal\w*\b", prior, re.I) else None
    if re.fullmatch(r"sağlamlıq məlumatları", current, re.IGNORECASE):
        if re.search(r"\b(?:fərdi|şəxsi) məlumat\w*\b", prior, re.IGNORECASE):
            return f"{heading} mövzusunda sağlamlıq məlumatları necə qorunur?"
        return None
    if match := re.fullmatch(r"bu\s+müddət\s+((?:neçə\s+.+)|nə qədərdir)", current, re.IGNORECASE):
        if not re.search(r"\b(?:müddət\w*|vaxt\w*|qüvvədə|müqavilə\w*|il|gün)\b", prior, re.IGNORECASE):
            return None
        subject = heading if re.search(r"\bmüddət\w*$", heading, re.IGNORECASE) else f"{heading} üzrə müddət"
        return f"{subject} {match[1]}?"
    if match := re.fullmatch(r"bu\s+qayda\s+(.+\baiddir)", current, re.IGNORECASE):
        return f"{heading} ilə bağlı qayda {match[1]}?"
    if current and not FOLLOW_UP.match(current) and AZ_QUESTION_WORD.search(current):
        return f"{heading} mövzusunda {current}?"
    return None


def resolve_query(original: str, history: list[str], *, direct_article: bool = False) -> QueryResolution:
    current = follow_up_text(original)
    if direct_article or not is_follow_up(original):
        return QueryResolution(original, original, history=tuple(history))

    # A fully specified new product question can start with a conversational connective.
    new_question = re.sub(r"^bəs\s*[,]?\s*", "", current, flags=re.IGNORECASE)
    if (new_question != current and not FOLLOW_UP.match(new_question)
            and PRODUCT.search(new_question) and AZ_QUESTION_WORD.search(new_question)):
        return QueryResolution(original, new_question + "?", history=tuple(history))
    prior = _prior_anchor(history)
    if prior is None:
        return QueryResolution(original, None, history=tuple(history))
    prior = " ".join(prior.split())
    if ELLIPTICAL_INSURANCE_FOLLOW_UP.fullmatch(current):
        standalone = f"{prior.rstrip('?.!')}. {current}?"
    elif re.match(r"^(?:bəs|bu|həmin|digər)\b", current, re.IGNORECASE):
        standalone = _azerbaijani_question(current, prior)
    elif match := re.fullmatch(r"(?:what|how) about (exclusions|exceptions|limits|deadlines)", current, re.IGNORECASE):
        topic = re.sub(r"^(?:what (?:is|are)|how does|tell me about)\s+|\s+work$", "", prior.rstrip("?.!"),
                       flags=re.IGNORECASE).strip()
        standalone = f"What {match[1].lower()} apply to {topic}?" if topic else None
    else:
        standalone = None
    return QueryResolution(original, standalone, (prior,) if standalone else (), tuple(history))


def follow_up_clarification(original: str, language: str) -> str:
    if language == "az" and BARE_CASE.fullmatch(follow_up_text(original)):
        return "Nəzərdə tutduğunuz halı qısaca təsvir edə bilərsinizmi?"
    return get_clarification(language)
