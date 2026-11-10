"""Free-text guard for records that must never carry protected traits (Fair Housing Rules 2 and 5;
comparison item 5). Used by the decision log now and by the weekly keyword scan (item 13) later.

The list is deliberately short and whole-word: it catches the obvious cases so a reason like
"income below the written 2.5x threshold" passes and "declined, disability" does not. It is a guard,
not a reviewer; Paul and counsel own the written criteria."""
import re

PROTECTED_TERMS: tuple[str, ...] = (
    # race, color, religion, national origin
    "race", "racial", "ethnic", "ethnicity", "religion", "religious", "church", "mosque", "synagogue",
    "national origin", "nationality", "immigrant", "immigration", "citizenship", "accent",
    # sex, familial status
    "sex", "gender", "pregnant", "pregnancy", "children", "child", "kids", "family status",
    "familial", "single mother", "single father", "married", "unmarried",
    # disability, health, and the care words banned in Rule 2
    "disability", "disabled", "handicap", "handicapped", "wheelchair", "medical", "medication",
    "diagnosis", "diagnosed", "mental", "psychiatric", "therapy", "treatment", "recovery", "sober",
    "sobriety", "addiction", "alcoholic", "service animal", "support animal", "emotional support",
    "care", "supervision", "assisted",
    # other statuses the org rules keep out of records
    "veteran", "voucher", "section 8",
)

_PATTERN = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(PROTECTED_TERMS, key=len, reverse=True))
                      + r")\b", re.IGNORECASE)


def protected_term_hits(text: str) -> list[str]:
    """Return the distinct protected-trait terms found in `text`, lower-cased, in order of appearance."""
    seen: list[str] = []
    for m in _PATTERN.finditer(text or ""):
        t = m.group(1).lower()
        if t not in seen:
            seen.append(t)
    return seen
