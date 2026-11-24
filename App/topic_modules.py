import re
from decimal import Decimal, ROUND_HALF_UP

from App.system import citation_for

HEALTH_SALARY_CLAUSE = "15-10.1.2"
SALARY_AMOUNT = re.compile(
    r"\b(?:maaş\w*|əmək\s*haqq\w*)\s*(?:[:=]\s*)?"
    r"(?P<amount>\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d.,])",
    re.IGNORECASE,
)
EMPLOYEE_HEALTH_RATE = re.compile(
    r"sığortaolunan tərəfindən əməkhaqqının\s+(\d+)\s+manatadək olan hissəsindən\s+"
    r"(\d+(?:[.,]\d+)?)\s+faiz,\s+\1\s+manatdan yuxarı olan hissəsindən\s+(\d+(?:[.,]\d+)?)\s+faiz",
    re.IGNORECASE,
)


def salary_insurance_request(text: str) -> tuple[Decimal, bool] | None:
    normalized = text.casefold().replace("\u0307", "")
    if not re.search(r"\b(?:sığorta|sigorta)\w*\b", normalized) or not re.search(r"\b(?:illik|ildə|il ərzində)\b", normalized):
        return None
    if re.search(r"\b(?:sosial|pensiya|dsmf|işsizlik|qəza|peşə|hərbi|net|xalis|avtomobil|həyat|usd|eur|dollar|avro)\w*\b|[$€]", normalized):
        return None
    match = SALARY_AMOUNT.search(normalized)
    if not match or re.search(r"\b(?:illik|ildə)\s*$", normalized[:match.start()]):
        return None
    salary = Decimal(re.sub(r"\s+", "", match["amount"]).replace(",", "."))
    if not 0 < salary <= 1_000_000_000_000:
        return None
    return salary, bool(re.search(r"\btibbi\b", normalized))


def salary_health_answer(salary: Decimal, explicit_health: bool, provision: str) -> str | None:
    match = EMPLOYEE_HEALTH_RATE.search(provision)
    if not match:
        return None
    threshold, base_rate, excess_rate = (Decimal(value.replace(",", ".")) for value in match.groups())
    monthly = (min(salary, threshold) * base_rate + max(salary - threshold, 0) * excess_rate) / 100
    monthly = monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def display(value: Decimal) -> str:
        return format(value.normalize(), "f").replace(".", ",")

    condition = "İcbari tibbi sığorta üzrə, aylıq brüt maaşınız" if explicit_health else "Əgər icbari tibbi sığortanı nəzərdə tutursunuzsa və aylıq brüt maaşınız"
    answer = (
        f"{condition} **{display(salary)} AZN**-dirsə, maddədə göstərilən dərəcələrlə hesablanan işçi payı ayda **{display(monthly)} AZN**, "
        f"eyni maaşla **12 ay** üçün isə **{display(monthly * 12)} AZN** edir [S1]."
    )
    if not explicit_health:
        answer += "\n\nSosial sığortanı, yoxsa başqa sığorta növünü nəzərdə tutursunuz?"
    return answer

MEASUREMENT = re.compile(
    r"(?<!\w)(?:\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(?:%|faiz\w*|процент\w*|(?:iş\s+|təqvim\s+|working\s+|calendar\s+|рабоч\w*\s+)?"
    r"(?:gün\w*|ay\w*|il\w*|days?\b|months?\b|years?\b|дн\w*|месяц\w*|лет\b)|"
    r"AZN\b|manat\w*|манат\w*)",
    re.IGNORECASE,
)


def extract_limits(hits: list[dict]) -> list[dict]:
    rows = []
    for hit in hits:
        text = hit["text"]
        for match in MEASUREMENT.finditer(text):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 90)
            rows.append({"value": match.group().strip(), "excerpt": text[start:end].strip(),
                         "source": citation_for(hit)})
    return rows
