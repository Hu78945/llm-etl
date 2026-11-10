"""Offline extractor: deterministic regex/rule-based extraction (no API key needed).

Used when ANTHROPIC_API_KEY is unset, and as the baseline the LLM is measured against.
Returns *candidate* fields; the JobPosting schema decides whether they are valid.
"""

import re

from llm_etl.schema import TAXONOMY

TITLE_PATTERNS = [
    re.compile(r"^Job Title:\s*(.+)$", re.MULTILINE),
    re.compile(r"is hiring an? (.+?) to join"),
    re.compile(r"looking for an? (.+?) who\b"),
]
ROLE_WORD = re.compile(r"\b(Engineer|Developer|Scientist|Analyst|Architect)\b", re.IGNORECASE)

SENIORITY_RULES = [  # first match wins; checked against the title
    ("lead", re.compile(r"\blead\b", re.IGNORECASE)),
    ("staff", re.compile(r"\b(staff|principal)\b", re.IGNORECASE)),
    ("senior", re.compile(r"\b(senior|sr)\b|\bIII$", re.IGNORECASE)),
    ("junior", re.compile(r"\b(junior|jr|associate|graduate|entry[- ]level|intern)\b|\bI$", re.IGNORECASE)),
]

# Longest aliases first so "Azure Data Factory" is consumed before "Azure" can match inside it.
_ALIASES = sorted(((a, s) for s, aliases in TAXONOMY.items() for a in aliases), key=lambda x: -len(x[0]))
SKILL_PATTERNS = [(re.compile(rf"(?<![\w-]){re.escape(a)}(?![\w-])", re.IGNORECASE), s) for a, s in _ALIASES]

CURRENCY_OF = {"$": "USD", "€": "EUR", "£": "GBP", "USD": "USD", "EUR": "EUR", "GBP": "GBP"}
_AMT = r"([$€£])?\s?(\d{1,3}(?:[.,]\d{3})+|\d+)([kK])?"
SALARY_RANGE = re.compile(rf"(?:\b(USD|EUR|GBP)\s)?{_AMT}\s*(?:-|–|to)\s*{_AMT}(?:\s?(USD|EUR|GBP)\b)?")
SALARY_SINGLE = re.compile(r"salary:?\s*([$€£])\s?(\d{1,3}(?:[.,]\d{3})+)", re.IGNORECASE)

REMOTE_RULES = [  # order matters: hybrid text often says "on-site", on-site text may say "remote-friendly"
    ("hybrid", re.compile(r"\bhybrid\b", re.IGNORECASE)),
    ("onsite", re.compile(r"\bon-?site\b|\boffice-based\b|\bin[- ]office\b", re.IGNORECASE)),
    ("remote", re.compile(r"\bremote\b|work from anywhere|work from home", re.IGNORECASE)),
]
LOCATION = re.compile(
    r"(?:Location:\s*|\|\s*|\b(?:in|from) (?:our )?)"  # context that introduces a place ...
    r"([A-Z][A-Za-z]+(?: [A-Z][a-z]+)?, [A-Z][A-Za-z]+)"  # ... followed by "City, Region"
)


def _title(text: str) -> str | None:
    for p in TITLE_PATTERNS:
        if m := p.search(text):
            return m.group(1).strip()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("["):
            return line.split("|")[0].strip() if ROLE_WORD.search(line) else None
    return None


def _seniority(title: str | None) -> str:
    for level, pattern in SENIORITY_RULES:
        if title and pattern.search(title):
            return level
    return "mid"  # no level marker in the title ("Data Engineer", "Data Engineer II")


def _skills(text: str) -> list[str]:
    found = set()
    for pattern, skill in SKILL_PATTERNS:
        if pattern.search(text):
            found.add(skill)
            text = pattern.sub(" ", text)  # mask, so shorter aliases can't re-match inside
    return sorted(found)


def _amount(num: str, k: str | None, other_has_k: bool) -> int:
    value = int(re.sub(r"[.,]", "", num))
    return value * 1000 if (k or other_has_k) and value < 1000 else value


def _salary(text: str) -> tuple[int | None, int | None, str | None]:
    for m in SALARY_RANGE.finditer(text):
        code1, sym1, n1, k1, sym2, n2, k2, code2 = m.groups()
        currency = code1 or sym1 or sym2 or code2
        if not currency:
            continue  # "0-2 years" etc.
        lo, hi = _amount(n1, k1, bool(k2)), _amount(n2, k2, bool(k1))
        return lo, hi, CURRENCY_OF[currency]
    if m := SALARY_SINGLE.search(text):
        value = int(re.sub(r"[.,]", "", m.group(2)))
        return value, value, CURRENCY_OF[m.group(1)]
    return None, None, None


def extract_fields(text: str) -> dict:
    title = _title(text)
    lo, hi, currency = _salary(text)
    remote = next((policy for policy, p in REMOTE_RULES if p.search(text)), None)
    loc = LOCATION.search(text)
    return {
        "title": title,
        "seniority": _seniority(title),
        "skills": _skills(text),
        "salary_min": lo,
        "salary_max": hi,
        "salary_currency": currency,
        "remote_policy": remote,
        "location": loc.group(1) if loc else None,
    }
