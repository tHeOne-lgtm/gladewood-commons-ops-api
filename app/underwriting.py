"""Underwriting math for a property: a port of the Gladewood Prospect Hub's uwInputs, uwReady, uwCalc,
uwProject, uwChecks and uwScenario (artifact BH7nsdF1LXHVEEfSqasFAz, read 2026-11-21). The reference copy of
the page's own JavaScript is tools/underwriting_reference.mjs and tests/test_underwriting_math.py checks this
module against values produced by it (tests/fixtures/underwriting_golden.json).

Pure functions, no database. Money is in dollars per month unless a name says otherwise. Results are planning
estimates, not financial advice (the page says the same).
"""
from __future__ import annotations

import re
from typing import Any

PROPERTY_STAGES = ["Found", "Contacted", "Toured", "Underwriting", "Negotiating", "Leased", "Passed"]
CLOSED_STAGES = {"Leased", "Passed"}
DEAL_TYPES = ("lease", "buy")
PROPERTY_SOURCES = ["Rental scout", "RentCast", "Claude research", "Zillow", "Craigslist", "Facebook Marketplace",
                    "Direct owner", "Agent or broker", "Referral"]

# Hub DEFAULT_SETTINGS, the keys underwriting reads. Stored per deployment in underwriting_settings; these are
# the values when a key has not been set.
DEFAULT_SETTINGS: dict[str, float] = {
    "planShared": 600, "planPrivate": 950, "targetOcc": 90, "utilitiesPerBed": 60, "internet": 80, "cleaning": 150,
    "supplies": 50, "furnishPerBed": 700,
    "uwMinCoverage": 1.3, "uwMaxBreakeven": 75, "uwMinCash": 300, "uwMinCoC": 15, "uwMinDSCR": 1.25, "uwMinCap": 6,
    "uwRepairsPct": 5, "uwReservePerBed": 25, "uwInsurance": 100, "uwMarketing": 50, "uwCreditLoss": 2,
    "uwGrowth": 3, "uwReserveMonths": 2,
}

# Per-property overrides the page stores under record.uw. Anything else sent is dropped.
INPUT_KEYS = (
    "mode", "privRent", "sharedRent", "occ", "creditLoss", "otherIncome", "leaseEsc", "deposit", "internet",
    "cleaning", "supplies", "insurance", "marketing", "repairsPct", "mgmtPct", "reservePerBed", "growth", "expGrowth",
    "furnishPerBed", "makeReady", "setupCosts", "reserveMonths", "price", "downPct", "rate", "years", "closingPct",
    "taxAnnual", "insAnnual",
)

SCENARIOS = [
    {"k": "cons", "label": "Conservative", "occ": -15, "rent": 0.9},
    {"k": "base", "label": "Base case", "occ": 0, "rent": 1},
    {"k": "up", "label": "Upside", "occ": 5, "rent": 1.05},
]

_STRIP = re.compile(r"[$,\s]")


def num(v: Any) -> float | None:
    """The page's num(): '$1,800' -> 1800.0; blanks and junk -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _STRIP.sub("", str(v))
    m = re.match(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def money(v: float | None) -> str:
    n = num(v)
    if n is None:
        return "—"
    return ("-$" if n < 0 else "$") + f"{abs(round(n)):,}"


def _ratio(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}×"


def _pct(v: float | None, digits: int = 0) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def settings_with_defaults(stored: dict[str, Any] | None) -> dict[str, float]:
    st = dict(DEFAULT_SETTINGS)
    for k, v in (stored or {}).items():
        n = num(v)
        if k in DEFAULT_SETTINGS and n is not None:
            st[k] = n
    return st


def resolve_inputs(record: dict[str, Any], uw: dict[str, Any] | None, settings: dict[str, float] | None = None) -> dict[str, Any]:
    """uwInputs(): the record's room counts, lease cost, utilities and sale price plus the uw overrides, with
    settings defaults for anything blank."""
    st = settings_with_defaults(settings)
    u = uw or {}
    priv = num(record.get("privateRooms"))
    shared = num(record.get("sharedRooms"))
    if priv is None and shared is None:
        priv = num(record.get("bedrooms"))
    priv = priv or 0
    shared = shared or 0
    beds = priv + shared * 2

    def g(k: str, d: float) -> float:
        v = u.get(k)
        if v is None or v == "":
            return d
        n = num(v) if not isinstance(v, (int, float)) or isinstance(v, bool) else float(v)
        return d if n is None else n

    lease = num(record.get("leaseCost")) or 0
    util = num(record.get("utilities"))
    return {
        "mode": "buy" if u.get("mode") == "buy" else "lease", "priv": priv, "shared": shared, "beds": beds,
        "privRent": g("privRent", st["planPrivate"]), "sharedRent": g("sharedRent", st["planShared"]),
        "occ": max(0.0, min(100.0, g("occ", st["targetOcc"]))), "creditLoss": g("creditLoss", st["uwCreditLoss"]),
        "otherIncome": g("otherIncome", 0),
        "lease": lease, "leaseEsc": g("leaseEsc", 3), "deposit": g("deposit", lease),
        "util": beds * st["utilitiesPerBed"] if util is None else util,
        "internet": g("internet", st["internet"]), "cleaning": g("cleaning", st["cleaning"]), "supplies": g("supplies", st["supplies"]),
        "insurance": g("insurance", st["uwInsurance"]), "marketing": g("marketing", st["uwMarketing"]),
        "repairsPct": g("repairsPct", st["uwRepairsPct"]), "mgmtPct": g("mgmtPct", 0), "reservePerBed": g("reservePerBed", st["uwReservePerBed"]),
        "growth": g("growth", st["uwGrowth"]), "expGrowth": g("expGrowth", 3),
        "furnishPerBed": g("furnishPerBed", st["furnishPerBed"]), "makeReady": g("makeReady", 0), "setupCosts": g("setupCosts", 0),
        "reserveMonths": g("reserveMonths", st["uwReserveMonths"]),
        "price": g("price", num(record.get("salePrice")) or 0), "downPct": g("downPct", 25), "rate": g("rate", 7),
        "years": max(1.0, g("years", 30)), "closingPct": g("closingPct", 3),
        "taxAnnual": g("taxAnnual", 0), "insAnnual": g("insAnnual", 0),
    }


def missing(i: dict[str, Any]) -> list[str]:
    """uwReady(): what has to be filled in before the model runs."""
    miss = []
    if i["beds"] == 0:
        miss.append("planned rooms or bedrooms")
    if i["mode"] == "lease" and not i["lease"]:
        miss.append("monthly lease cost")
    if i["mode"] == "buy" and not i["price"]:
        miss.append("purchase price")
    return miss


def calc(i: dict[str, Any], occ: float | None = None, rent_mult: float | None = None) -> dict[str, Any]:
    """uwCalc(): one month at the given occupancy and rent multiplier."""
    o = max(0.0, min(100.0, i["occ"] if occ is None else occ)) / 100
    rm = 1.0 if rent_mult is None else rent_mult
    buy = i["mode"] == "buy"
    gpr = (i["priv"] * i["privRent"] + i["shared"] * 2 * i["sharedRent"]) * rm
    rented = gpr * o
    vacancy = gpr - rented
    credit = rented * i["creditLoss"] / 100
    egi = rented - credit + i["otherIncome"]
    insurance = i["insAnnual"] / 12 if buy else i["insurance"]
    tax = i["taxAnnual"] / 12 if buy else 0
    reserve = i["reservePerBed"] * i["beds"]
    fixed = i["util"] + i["internet"] + i["cleaning"] + i["supplies"] + insurance + i["marketing"] + reserve + tax
    pct = (i["repairsPct"] + i["mgmtPct"]) / 100
    repairs = egi * i["repairsPct"] / 100
    mgmt = egi * i["mgmtPct"] / 100
    opex = fixed + repairs + mgmt
    noi = egi - opex
    loan = i["price"] * (1 - i["downPct"] / 100) if buy else 0
    mr = i["rate"] / 1200
    n = i["years"] * 12
    if buy and loan > 0:
        pmt = loan * mr / (1 - (1 + mr) ** (-n)) if mr > 0 else loan / n
    else:
        pmt = 0
    fin = pmt if buy else i["lease"]
    cash = noi - fin
    furnish = i["beds"] * i["furnishPerBed"]
    reserves = i["reserveMonths"] * (fixed + fin)
    down = i["price"] * i["downPct"] / 100 + i["price"] * i["closingPct"] / 100 if buy else i["deposit"]
    upfront = down + furnish + i["makeReady"] + i["setupCosts"] + reserves
    coverage = noi / fin if fin > 0 else None
    coc = cash * 12 / upfront if upfront > 0 else None
    payback = upfront / cash if cash > 0 and upfront > 0 else None
    cap = noi * 12 / i["price"] if buy and i["price"] > 0 else None
    grm = i["price"] / (gpr * 12) if buy and gpr > 0 else None
    egi_star = (fixed + fin) / (1 - pct) if pct != 1 else None
    breakeven = ((egi_star - i["otherIncome"]) / (1 - i["creditLoss"] / 100)) / gpr if gpr > 0 and egi_star is not None and i["creditLoss"] != 100 else None
    beds = i["beds"] or 1
    return {
        "gpr": gpr, "vacancy": vacancy, "credit": credit, "other": i["otherIncome"], "egi": egi,
        "util": i["util"], "internet": i["internet"], "cleaning": i["cleaning"], "supplies": i["supplies"],
        "insurance": insurance, "marketing": i["marketing"], "repairs": repairs, "mgmt": mgmt, "reserve": reserve, "tax": tax,
        "fixed": fixed, "opex": opex, "noi": noi, "loan": loan, "pmt": pmt, "fin": fin, "cash": cash, "annual": cash * 12,
        "furnish": furnish, "reserves": reserves, "upfront": upfront, "coverage": coverage, "coc": coc, "payback": payback,
        "cap": cap, "grm": grm, "breakeven": breakeven,
        "perBedRevenue": egi / beds, "perBedCost": (opex + fin) / beds, "perBedProfit": cash / beds, "occ": o * 100, "buy": buy,
    }


def project(i: dict[str, Any], years: int = 5) -> list[dict[str, float]]:
    """uwProject(): yearly cash flow with rent, expense and lease growth, and the running total after upfront cash."""
    base = calc(i)
    rows = []
    cum = -base["upfront"]
    for y in range(1, years + 1):
        gf = (1 + i["growth"] / 100) ** (y - 1)
        ef = (1 + i["expGrowth"] / 100) ** (y - 1)
        egi = base["egi"] * gf
        fixed = base["fixed"] * ef
        noi = egi - fixed - egi * (i["repairsPct"] + i["mgmtPct"]) / 100
        fin = base["pmt"] if i["mode"] == "buy" else i["lease"] * (1 + i["leaseEsc"] / 100) ** (y - 1)
        cf = (noi - fin) * 12
        cum += cf
        rows.append({"y": y, "egi": egi * 12, "noi": noi * 12, "fin": fin * 12, "cf": cf, "cum": cum})
    return rows


def checks(i: dict[str, Any], c: dict[str, Any], settings: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """uwChecks(): the targets from settings, each with a pass flag."""
    st = settings_with_defaults(settings)
    buy = i["mode"] == "buy"
    min_cov = st["uwMinDSCR"] if buy else st["uwMinCoverage"]
    out = [
        {"label": "Debt service coverage" if buy else "Rent coverage", "value": _ratio(c["coverage"]),
         "target": f"at least {min_cov:.2f}×", "ok": c["coverage"] is not None and c["coverage"] >= min_cov},
        {"label": "Break-even occupancy", "value": "—" if c["breakeven"] is None else f"{round(c['breakeven'] * 100)}%",
         "target": f"at most {st['uwMaxBreakeven']:g}%", "ok": c["breakeven"] is not None and c["breakeven"] * 100 <= st["uwMaxBreakeven"]},
        {"label": "Cash flow per month", "value": money(c["cash"]), "target": "at least " + money(st["uwMinCash"]),
         "ok": c["cash"] >= st["uwMinCash"]},
        {"label": "Cash-on-cash return", "value": "—" if c["coc"] is None else f"{round(c['coc'] * 100)}%",
         "target": f"at least {st['uwMinCoC']:g}%", "ok": c["coc"] is not None and c["coc"] * 100 >= st["uwMinCoC"]},
    ]
    if buy:
        out.append({"label": "Cap rate", "value": "—" if c["cap"] is None else f"{c['cap'] * 100:.1f}%",
                    "target": f"at least {st['uwMinCap']:g}%", "ok": c["cap"] is not None and c["cap"] * 100 >= st["uwMinCap"]})
    return out


def scenarios(i: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """uwScenario() for each of UW_SCEN."""
    return {s["k"]: calc(i, occ=min(100.0, i["occ"] + s["occ"]), rent_mult=s["rent"]) for s in SCENARIOS}


def summary_text(address: str, i: dict[str, Any], c: dict[str, Any], chk: list[dict[str, Any]], today: str) -> str:
    """uwSummaryText(): the copy-to-text block."""
    buy = i["mode"] == "buy"
    sc = scenarios(i)
    lines = [
        f"Underwriting: {address} ({'purchase' if buy else 'master lease'}, {i['beds']:g} beds)",
        f"Cash flow {money(c['cash'])}/mo · {'debt coverage' if buy else 'rent coverage'} {_ratio(c['coverage'])} · "
        f"cash-on-cash {_pct(c['coc'])} · break-even occupancy {_pct(c['breakeven'])} · cash to start {money(c['upfront'])}",
        f"At {round(c['occ'])}% occupancy, income {money(c['egi'])}/mo, operating costs {money(c['opex'])}/mo, "
        f"{'loan payment' if buy else 'rent'} {money(c['fin'])}/mo.",
    ]
    for s in SCENARIOS:
        x = sc[s["k"]]
        lines.append(f"{s['label']}: {money(x['cash'])}/mo, coverage {_ratio(x['coverage'])}")
    lines.append(f"Targets met: {sum(1 for x in chk if x['ok'])} of {len(chk)}.")
    lines.append(f"Planning estimate, not financial advice. {today}")
    return "\n".join(lines)


def csv_rows(address: str, i: dict[str, Any], c: dict[str, Any]) -> list[list[Any]]:
    """uwCSV(): the rows of the CSV export."""
    buy = i["mode"] == "buy"
    rows = [
        ["Item", "Value"], ["Property", address], ["Deal type", "Purchase" if buy else "Master lease"], ["Beds", f"{i['beds']:g}"],
        ["Occupancy %", round(c["occ"])], ["Gross potential rent / mo", round(c["gpr"])], ["Effective income / mo", round(c["egi"])],
        ["Operating costs / mo", round(c["opex"])], ["Operating income before rent or loan / mo", round(c["noi"])],
        ["Loan payment / mo" if buy else "Rent / mo", round(c["fin"])], ["Cash flow / mo", round(c["cash"])],
        ["Coverage", "" if c["coverage"] is None else f"{c['coverage']:.2f}"],
        ["Cash-on-cash %", "" if c["coc"] is None else f"{c['coc'] * 100:.1f}"],
        ["Break-even occupancy %", "" if c["breakeven"] is None else f"{c['breakeven'] * 100:.1f}"],
        ["Cash to start", round(c["upfront"])],
    ]
    sc = scenarios(i)
    for s in SCENARIOS:
        rows.append([s["label"] + " cash flow / mo", round(sc[s["k"]]["cash"])])
    return rows
