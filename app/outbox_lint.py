"""Deterministic pre-flight lint for every outbox row (Atlas gap 2, gate 1). No AI.

A Python port of the A4 Draft Check scan (`~/gladewood-n8n/a4-linter/a4-scan.js`, as published
2026-11-20) plus the CRM's protected-trait list. Failures hold the row at dispatch and block approval;
notes travel with the row and never block. The exact disclaimer is cut out before the scan because it
carries care words on purpose.
"""
import re
from dataclasses import dataclass, field

from app.fair_housing import protected_term_hits

TEXT_CHANNELS = ("sms", "whatsapp")
SMS_HARD_LIMIT = 1600        # Twilio's body limit
SMS_NOTE_LIMIT = 320         # two segments
EMAIL_NOTE_WORDS = 250       # the voice profile's email limit

# Fact Sheet key `disclaimer` (owner wording 2026-11-12). Keep it byte-for-byte equal to the sheet.
DISCLAIMER = ("Gladewood Commons is an independent, all-inclusive co-living housing rental company. We are not a care "
              "facility and do not provide on-site medical care, supervision, medication administration, or assistance "
              "with activities of daily living. Gladewood Commons provides housing and property management only.")

_I = re.IGNORECASE
BANNED: tuple[tuple[str, re.Pattern], ...] = (
    ("ideal for", re.compile(r"\bideal for\b", _I)), ("good fit", re.compile(r"\bgood fit\b", _I)),
    ("perfect for", re.compile(r"\bperfect for\b", _I)), ("adults only", re.compile(r"\badults only\b", _I)),
    ("working professionals", re.compile(r"\bworking professionals?\b", _I)),
    ("independent adults", re.compile(r"\bindependent adults?\b", _I)), ("mature", re.compile(r"\bmature\b", _I)),
    ("no children", re.compile(r"\bno children\b", _I)), ("singles", re.compile(r"\bsingles\b", _I)),
    ("affordable", re.compile(r"\baffordable\b", _I)), ("housing for", re.compile(r"\bhousing for\b", _I)),
    ("belong", re.compile(r"\bbelong\b", _I)), ("comfortable", re.compile(r"\bcomfortable\b", _I)),
    ("care", re.compile(r"\bcare\b", _I)), ("support", re.compile(r"\bsupport(ive)?\b", _I)),
    ("supervision", re.compile(r"\bsupervis", _I)), ("assisted", re.compile(r"\bassisted\b", _I)),
    ("recovery", re.compile(r"\brecovery\b", _I)), ("treatment", re.compile(r"\btreatment\b", _I)),
    ("medication", re.compile(r"\bmedication", _I)), ("daily living", re.compile(r"\bdaily living\b", _I)),
    ("season", re.compile(r"\b(this|next) (fall|spring|summer|winter)\b", _I)),
    ("opening date", re.compile(r"\bopening (in|on|by) (january|february|march|april|may|june|july|august|september|october|november|december)\b", _I)),
    ("testimonial or count", re.compile(r"\btestimonial|\b\d+ (residents|tenants|people) (live|placed|housed)\b", _I)),
    ("pets or animals", re.compile(r"\b(pets?|animals?)\b", _I)),
    ("em or en dash", re.compile(r"[–—]")),
    ("familial", re.compile(r"\b(no kids|child[- ]?free|families|family[- ]friendly|bachelors?|couples?|newlyweds?|empty nest|retired|seniors?|students? only)\b", _I)),
    ("religion", re.compile(r"\b(church|christian|catholic|jewish|muslim|mosque|synagogue|bible|religious|faith)\b", _I)),
    ("sex", re.compile(r"\b(male|female|men|women|ladies|gentlemen|girls?|guys?)\b", _I)),
    ("disability", re.compile(r"\b(disabled|handicap(ped)?|able[- ]bodied|healthy|sober|special needs|impair(ed|ment))\b", _I)),
    ("origin", re.compile(r"\b(english[- ]speaking|citizens? only|foreigners?|immigrants?|ethnic|racial|race|hispanic|latino|latina)\b", _I)),
    ("steering", re.compile(r"\b(exclusive|restricted|desirable neighborhood|safe neighborhood|good neighborhood)\b", _I)),
    # gap 3 additions (2026-11-20)
    ("health detail", re.compile(r"\b(diagnos\w*|psychiatric|clinical notes?|medical (records?|history)|schizophren\w*|bipolar|PTSD|dementia|HIV|prescri(ption|bed|ptions)|dosage|addict\w*|rehab\w*|detox|overdose|relapse|discharge (plan|summary)|case plan|therapy|inpatient)\b", _I)),
    ("door or lock code", re.compile(r"\b(?:(?:door|lock|gate|keypad|entry|access)\s+(?:code|pin)|pin|passcode)\b[^\d\n]{0,12}\b\d{4,8}\b", _I)),
    ("instruction text", re.compile(r"\b(ignore|disregard|forget)\b[^.\n]{0,30}\b(previous|prior|above|earlier|all)\b[^.\n]{0,20}\binstructions?\b|\b(system prompt|developer mode|as an ai\b|you are (now )?an? (ai|assistant|language model))", _I)),
    ("personal identifier", re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(date of birth|DOB|social security|SSN|driver'?s licen[cs]e number)\b", _I)),
)
VOICE_WORDS = re.compile(r"\b(tapestry|beacon|testament|symphony|journey|navigate|landscape|delve|foster|garner|bolster|underscore|pivotal|paramount|vital|furthermore|moreover|additionally|in conclusion|firstly|secondly|lastly|seamless|dynamic|transformative|robust|meticulous|holistic|unwavering|synergy|paradigm|exceptional|genuinely|leverage|utilize|hope this (email )?finds you well|do not hesitate|per my (previous|last) email|fast-paced|in order to|due to the fact)\b", _I)
_PRICE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?([MK])?\b", _I)


def _amount(number: str, suffix: str | None) -> float:
    v = float(number.replace(",", ""))
    return v * {"k": 1_000.0, "m": 1_000_000.0}.get((suffix or "").lower(), 1.0)


def allowed_prices(spec: str) -> set[float]:
    """OUTBOX_ALLOWED_PRICES: space-separated figures copied from the Fact Sheet, for example
    "550 650 850 1100 350 1M 2M". A dollar sign and thousands commas are fine inside a token."""
    out: set[float] = set()
    for tok in (spec or "").split():
        m = _PRICE.fullmatch("$" + tok.lstrip("$"))
        if m:
            out.add(_amount(m.group(1), m.group(2)))
    return out


@dataclass
class LintResult:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    words: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict:
        return {"ok": self.ok, "failures": self.failures, "notes": self.notes, "words": self.words}


def lint_text(channel: str, subject: str, body: str, allowed: str = "") -> LintResult:
    text = f"{subject}\n{body}" if subject else (body or "")
    scan = text.replace(DISCLAIMER, " ")
    r = LintResult(words=len(re.findall(r"\S+", text)))
    matched: set[str] = set()
    for label, pat in BANNED:
        m = pat.search(scan)
        if m:
            r.failures.append(f'{label}: "{m.group(0)}"')
            matched.add(m.group(0).lower())
    for term in protected_term_hits(scan):
        if term not in matched:
            r.failures.append(f'protected term: "{term}"')
    ok_prices = allowed_prices(allowed)
    for m in _PRICE.finditer(scan):
        if _amount(m.group(1), m.group(2)) not in ok_prices:
            r.failures.append(f'unconfirmed price: "{m.group(0).strip()}"')
    if channel in TEXT_CHANNELS:
        if len(body or "") > SMS_HARD_LIMIT:
            r.failures.append(f"text is {len(body)} characters; the limit is {SMS_HARD_LIMIT}")
        elif len(body or "") > SMS_NOTE_LIMIT:
            r.notes.append(f"text is {len(body)} characters, more than two segments")
    elif r.words > EMAIL_NOTE_WORDS:
        r.notes.append(f"email is {r.words} words; the profile limit is {EMAIL_NOTE_WORDS}")
    voice = sorted({m.group(0).lower() for m in VOICE_WORDS.finditer(scan)})
    if voice:
        r.notes.append("voice words to swap: " + ", ".join(voice))
    # one entry per distinct failure, in order
    seen: list[str] = []
    for f in r.failures:
        if f not in seen:
            seen.append(f)
    r.failures = seen
    return r
