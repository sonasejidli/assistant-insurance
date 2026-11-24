from __future__ import annotations

import os
import re
from typing import Literal

from langchain_openrouter import ChatOpenRouter

from App.azerbaijani import ascii_key, normalize_az
from App.insurance_terminology import TERMINOLOGY
from App.observability import tracing_config
from App.settings import API_KEY, LLM_MODEL


Intent = Literal[
    "greeting",
    "thanks",
    "goodbye",
    "bot_info",
    "insurance_question",
    "out_of_scope",
]


INTENT_LLM_ENABLED = os.getenv("INTENT_LLM_ENABLED", "").casefold() in {"1", "true", "yes"}
SOCIAL_INTENTS = {"greeting", "thanks", "goodbye", "bot_info"}


_GREETINGS = re.compile(
    r"\b(?:salam|salamlar|salam aleykum|hello|hi|hey|good morning|good afternoon|good evening|привет|здравствуй|здравствуйте|добрый день)\b",
    re.IGNORECASE,
)
_THANKS = re.compile(
    r"\b(?:təşəkkür(?: edirəm)?|tesekkur(?: edirem)?|çox sağ olun?|cox sag olun?|sağ ol|sag ol|thanks(?: a lot)?|thank you(?: very much)?|(?:большое )?спасибо|spasibo)\b",
    re.IGNORECASE,
)
_GOODBYES = re.compile(
    r"\b(?:hələlik|helelik|görüşərik|gorusərik|sağ olun|bye|goodbye|see you(?: later)?|пока|до свидания)\b",
    re.IGNORECASE,
)
_BOT_INFO = re.compile(
    r"(?:kimsən|sən kimsən|siz kimsiniz|nə edə bilərsən|nə iş görürsən|who are you|what can you do|(?:tell me )?about you(?:rself)?|ты кто|кто ты|кто вы|что ты умеешь)",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_HINT = re.compile(
    r"\b(?:weather|forecast|temperature|hava|hava\s+durumu|погода|прогноз)\b",
    re.IGNORECASE,
)

_WORKPLACE_ACCIDENT = re.compile(
    r"\b(?:istehsalat\w*|iş\s+yeri\w*|işdə)\b.*\b(?:bədbəxt\s+hadisə\w*|qəza\w*)\b|\biş\s+qəza\w*\b",
    re.IGNORECASE,
)

_INSURANCE_HINT = re.compile(
    r"\b(?:sığorta\w*|sigorta\w*|icbari|tibbi|iş qəzası|qəza|hərbi|sosial|auditor|qanun\w*|maddə\w*|bənd|müddət|vaxt|tarif|ödəniş\w*|müavinət\w*|insurance|premiums?|claims?|policy|policies|law|articles?|clause|deadline|time\s+limit|limits?|tariff|exclusions?|subrogation|страхов\w*|страхование|полис\w*|выплат\w*|срок\w*|стать\w*|пункт\w*)\b",
    re.IGNORECASE,
)

_REFERRAL = re.compile(r"\bgonderis\w*\b")
_REFERRAL_PROVIDER = re.compile(r"\b(?:poliklinika\w*|aile\s+hekim\w*)\b")
_ACCESS_WITHOUT_REFERRAL = re.compile(r"\bgonderis\w*\s+olmadan\b")
_SERVICE_ACCESS = re.compile(r"\bxidmet\w*\b.*\b(?:yararlan\w*|istifade\s+et\w*)\b")
_OCCUPATIONAL_DISEASE = re.compile(r"\bpese\s+xesteli(?:k|y)\w*\b")
_DISABILITY_PAYMENT = re.compile(
    r"^(?=.*\belilli(?:k|y)\w*\b)"
    r"(?=.*\bfunksiya\w*\s+pozul\w*\s+faiz\w*\b)"
    r"(?=.*\boden(?:il|ir)\w*\b)"
)
_BENEFIT_AND_COMPENSATION_HINTS = (
    # Birth registration or parental status without a benefit cue is insufficient.
    re.compile(r"^(?=.*\b(?:usaq\w*|usag\w*|korpe\w*)\b)"
               r"(?=.*\b(?:dogul\w*|dogum\w*|dunyaya\s+gel\w*)\b)"
               r"(?=.*\b(?:muavinet\w*|pul\w*|birdefelik\s+yardim\w*)\b)"),
    re.compile(r"^(?=.*\b(?:dogum\w*|dogul\w*)\b)(?=.*\bbirdefelik\s+(?:yardim|muavinet)\w*\b)"),
    re.compile(r"^(?=.*\bkompensasiya\w*\b)(?=.*\bimtina\w*\b)"),
    re.compile(r"^(?=.*\bmuqavile\w*\b)(?=.*\b(?:xitam\w*|legv\w*|bit\w*)\b)"
               r"(?=.*\b(?:hadise\w*|qeza\w*)\b)(?=.*\b(?:evvel\w*|bildiris\w*|kompensasiya\w*)\b)"),
    re.compile(r"^(?=.*\belilli(?:k|y)\w*\b)(?=.*\bfaiz\w*\b)"
               r"(?=.*\b(?:mebleg\w*|kompensasiya\w*)\b)"),
    re.compile(r"^(?=.*\b(?:funksiya\w*\s+(?:itki\w*|pozul\w*))\b)(?=.*\bfaiz\w*\b)"
               r"(?=.*\b(?:pul\w*|kompensasiya\w*)\b)"),
    re.compile(r"\bxestelik\s+pulu\b"),
    re.compile(r"^(?=.*\b(?:isde|istehsalat\w*)\b)(?=.*\b(?:yaralan\w*|xesaret\w*|zede\w*)\b)"
               r"(?=.*\b(?:kompensasiya\w*|oden\w*)\b)"),
    re.compile(r"^(?=.*\bagir\b)(?=.*\byungul\b)(?=.*\b(?:yaralan\w*|xesaret\w*|zede\w*)\b)"
               r"(?=.*\b(?:pul\w*|mebleg\w*|oden\w*|faiz\w*)\b)"),
)


def _medical_referral_question(text: str) -> bool:
    normalized = ascii_key(normalize_az(text))
    return bool(_REFERRAL.search(normalized) and (
        _REFERRAL_PROVIDER.search(normalized)
        or (_ACCESS_WITHOUT_REFERRAL.search(normalized) and _SERVICE_ACCESS.search(normalized))
    ))


def classify_intent_rule(text: str) -> Intent | None:
    cleaned = " ".join(text.split()).strip(" .,!?:;…")
    if not cleaned:
        return None

    if _GREETINGS.fullmatch(cleaned):
        return "greeting"
    if _THANKS.fullmatch(cleaned):
        return "thanks"
    if _GOODBYES.fullmatch(cleaned):
        return "goodbye"
    if _BOT_INFO.fullmatch(cleaned):
        return "bot_info"

    if _WORKPLACE_ACCIDENT.search(cleaned):
        return "insurance_question"

    if _OUT_OF_SCOPE_HINT.search(cleaned) and not re.search(r"\b(?:sığorta\w*|sigorta\w*|insurance)\b", cleaned, re.I):
        return "out_of_scope"

    # Only route directly to insurance_question when we have strong hints.
    folded = ascii_key(normalize_az(cleaned))
    if (_INSURANCE_HINT.search(cleaned) or _medical_referral_question(cleaned)
            or _OCCUPATIONAL_DISEASE.search(folded)
            or _DISABILITY_PAYMENT.match(folded)
            or any(hint.search(folded) for hint in _BENEFIT_AND_COMPENSATION_HINTS)
            or TERMINOLOGY.query_concepts(cleaned) & TERMINOLOGY.evidence_concepts):
        return "insurance_question"

    return None


def classify_intent_llm(text: str, language: str) -> Intent:
    if not INTENT_LLM_ENABLED or not API_KEY:
        return "out_of_scope"

    model = ChatOpenRouter(
        model=LLM_MODEL,
        api_key=API_KEY,
        temperature=0,
        max_tokens=10,
    )

    prompt = (
        "Classify the user message into exactly one label from: "
        "greeting, thanks, goodbye, bot_info, insurance_question, out_of_scope.\n"
        "Return ONLY the label.\n\n"
        f"Language hint: {language}\n"
        f"Message: {text}"
    )

    result = model.invoke(prompt, config=tracing_config())
    label = (getattr(result, "content", "") or "").strip().lower()
    mapping = {
        "greeting": "greeting",
        "thanks": "thanks",
        "goodbye": "goodbye",
        "bot_info": "bot_info",
        "insurance_question": "insurance_question",
        "out_of_scope": "out_of_scope",
    }
    return mapping.get(label, "out_of_scope")


def classify_intent(text: str, language: str) -> Intent:
    rule = classify_intent_rule(text)
    if rule is not None:
        return rule
    return classify_intent_llm(text, language)
