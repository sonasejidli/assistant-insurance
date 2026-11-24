import logging
from typing import Literal

from httpx import TimeoutException
from httpx2 import TimeoutException as SDKTimeoutException
from openrouter.errors import TooManyRequestsResponseError

from App.evaluation_capture import provider_error, record
from App.observability import event
from App.settings import API_KEY, LLM_MODEL


DeliveryFailure = Literal["verification_failed", "provider_rate_limit", "provider_timeout",
                          "provider_unavailable", "internal_error"]
log = logging.getLogger(__name__)

MESSAGES = {
    "verification_failed": {
        "az": "Cavabı etibarlı şəkildə yoxlamaq mümkün olmadı.",
        "en": "The answer could not be reliably verified.",
        "ru": "Не удалось надёжно проверить ответ.",
    },
    "provider_rate_limit": {
        "az": "Cavab xidməti müvəqqəti əlçatan deyil. Bir qədər sonra yenidən cəhd edin.",
        "en": "The answer service is temporarily unavailable. Please try again shortly.",
        "ru": "Сервис ответов временно недоступен. Повторите попытку чуть позже.",
    },
    "provider_timeout": {
        "az": "Cavab xidməti vaxtında cavab vermədi. Yenidən cəhd edin.",
        "en": "The answer service did not respond in time. Please try again.",
        "ru": "Сервис ответов не ответил вовремя. Повторите попытку.",
    },
    "provider_unavailable": {
        "az": "Cavab xidməti müvəqqəti işləmir. Bir qədər sonra yenidən cəhd edin.",
        "en": "The answer service is temporarily unavailable. Please try again shortly.",
        "ru": "Сервис ответов временно недоступен. Повторите попытку чуть позже.",
    },
    "internal_error": {
        "az": "Sorğunu emal etmək mümkün olmadı. Yenidən cəhd edin.",
        "en": "The request could not be processed. Please try again.",
        "ru": "Не удалось обработать запрос. Повторите попытку.",
    },
}


def provider_failure(exc: Exception, stage: str, *, fallback: DeliveryFailure = "internal_error",
                     model: str = LLM_MODEL, api_key: str = API_KEY, provider: str = "openrouter") -> DeliveryFailure:
    details = provider_error(exc, api_key)
    http_status = details.get("http_status")
    if isinstance(exc, TooManyRequestsResponseError) or http_status == 429:
        status = "provider_rate_limit"
    elif isinstance(exc, (TimeoutException, SDKTimeoutException, TimeoutError)) or http_status in {408, 504}:
        status = "provider_timeout"
    elif http_status is not None and 500 <= http_status < 600:
        status = "provider_unavailable"
    else:
        status = fallback
    record(answer_failure={"stage": stage, "model": model, "provider": provider, **details})
    event("answer_failure", failure_stage=stage, delivery_status=status, model=model, provider=provider,
          **{key: value for key, value in details.items() if key != "provider_message"})
    log.warning("Answer withheld at %s via %s (%s, HTTP %s)", stage, provider, type(exc).__name__, http_status)
    return status


def answer_recovery(status: DeliveryFailure, language: str) -> dict:
    return {"answer": "", "delivery_status": status, "delivery_message": MESSAGES[status][language],
            "answer_mode": None, "sources": [], "references": [], "warnings": [],
            "limits": [], "previews": [], "related_articles": [], "language": language}
