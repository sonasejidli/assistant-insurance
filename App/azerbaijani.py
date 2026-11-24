"""Conservative Azerbaijani nominal lemmatization for lexical retrieval."""

import re
import unicodedata
from collections import defaultdict
from functools import lru_cache

TOKEN = re.compile(r"\w+")
AZ_LOWER = str.maketrans({"I": "ı", "İ": "i"})
ASCII_FOLD = str.maketrans("əğıöüşç", "egiousc")
HIGH_VOWELS = dict(zip("aıeəiöüou", "ııiiiüüuu"))

# The second form gives the stem before a vowel-initial ending when it changes.
NOUNS = {
    "hesablama": "hesablama", "hesablanma": "hesablanma",
    "sığorta": "sığorta", "sığortalı": "sığortalı", "sığortaçı": "sığortaçı",
    "ödəniş": "ödəniş", "hədd": "hədd", "tarif": "tarif", "haqq": "haqq",
    "hadisə": "hadisə", "tələb": "tələb", "məbləğ": "məbləğ",
    "azadolma": "azadolma", "franşiza": "franşiza", "subroqasiya": "subroqasiya",
    "məsuliyyət": "məsuliyyət", "əmlak": "əmlak", "istisna": "istisna",
    "faydalanan": "faydalanan", "şəxs": "şəxs", "müddət": "müddət",
    "qanun": "qanun", "maddə": "maddə", "müqavilə": "müqavilə",
    "zərər": "zərər", "risk": "risk", "qayda": "qayda", "şərt": "şərt",
    "sənəd": "sənəd", "müraciət": "müraciət", "ərizə": "ərizə",
    "kompensasiya": "kompensasiya", "təminat": "təminat", "öhdəlik": "öhdəliy",
    "pul": "pul", "limit": "limit", "maşın": "maşın", "avtomobil": "avtomobil",
    "vasitə": "vasitə", "maaş": "maaş", "əməkhaqqı": "əməkhaqqı", "gəlir": "gəlir",
    "ödənilmə": "ödənilmə", "dəyər": "dəyər", "xidmət": "xidmət",
    "işçi": "işçi", "işəgötürən": "işəgötürən", "mənbə": "mənbə",
}
RETRIEVAL_EQUIVALENTS = {"hesablanma": "hesablama"}


def normalize_az(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(AZ_LOWER).lower()


def surface_tokens(text: str) -> list[str]:
    return TOKEN.findall(normalize_az(text))


def ascii_key(word: str) -> str:
    return word.translate(ASCII_FOLD)


def case_forms(base: str, vowel_stem: str, *, third_person: bool = False) -> set[str]:
    last_vowel = next(char for char in reversed(base) if char in HIGH_VOWELS)
    high = HIGH_VOWELS[last_vowel]
    low = "a" if last_vowel in "aıou" else "ə"
    if third_person:
        return {base, base + "n" + high + "n", base + "n" + high, base + "n" + low,
                base + "nd" + low, base + "nd" + low + "n"}
    if base[-1] in HIGH_VOWELS:
        return {base, base + "n" + high + "n", base + "y" + high, base + "y" + low,
                base + "d" + low, base + "d" + low + "n"}
    return {base, vowel_stem + high + "n", vowel_stem + high, vowel_stem + low,
            base + "d" + low, base + "d" + low + "n"}


def noun_forms(lemma: str, vowel_stem: str) -> set[str]:
    forms = set()
    last_vowel = next(char for char in reversed(lemma) if char in HIGH_VOWELS)
    plural = lemma + ("lar" if last_vowel in "aıou" else "lər")
    for base, stem in ((lemma, vowel_stem), (plural, plural)):
        last_vowel = next(char for char in reversed(base) if char in HIGH_VOWELS)
        high = HIGH_VOWELS[last_vowel]
        vowel_final = base[-1] in HIGH_VOWELS
        forms.update(case_forms(base, stem))
        link = "" if vowel_final else high
        for ending in ("m", "n", "m" + high + "z", "n" + high + "z"):
            possessive = stem + link + ending
            forms.update(case_forms(possessive, possessive))
        forms.update(case_forms(stem + ("s" if vowel_final else "") + high,
                                "", third_person=True))
    return forms


def unique_lemmas(candidates: dict[str, set[str]]) -> dict[str, str]:
    return {form: next(iter(lemmas)) for form, lemmas in candidates.items() if len(lemmas) == 1}


class AzerbaijaniLemmatizer:
    """Resolve only unambiguous forms of approved Azerbaijani lemmas."""

    def __init__(self, nouns: dict[str, str]):
        forms = defaultdict(set)
        ascii_forms = defaultdict(set)
        for lemma, vowel_stem in nouns.items():
            for form in noun_forms(lemma, vowel_stem):
                forms[form].add(lemma)
                ascii_forms[ascii_key(form)].add(lemma)
        self.known_lemmas = frozenset(nouns)
        self.forms = unique_lemmas(forms)
        self.ambiguous_forms = forms.keys() - self.forms.keys()
        self.ascii_forms = unique_lemmas(ascii_forms)

    @lru_cache(maxsize=16384)
    def lemmatize(self, word: str) -> str:
        word = normalize_az(word)
        if word in self.known_lemmas or word in self.ambiguous_forms:
            return word
        # Uppercase ASCII input passes through Azerbaijani I → ı casing first.
        ascii_spelling = word.replace("ı", "i")
        if ascii_spelling.isascii() and word not in self.forms:
            return self.ascii_forms.get(ascii_spelling, word)
        return self.forms.get(word, word)


LEMMATIZER = AzerbaijaniLemmatizer(NOUNS)
