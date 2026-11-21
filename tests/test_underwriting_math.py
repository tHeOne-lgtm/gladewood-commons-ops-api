"""app/underwriting.py against values produced by the Hub page's own JavaScript (tools/underwriting_golden.mjs)."""
import json
import math
from pathlib import Path

import pytest

from app import underwriting as uw

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "underwriting_golden.json").read_text())


def close(a, b, path=""):
    if isinstance(b, dict):
        assert isinstance(a, dict), path
        assert set(a) == set(b), (path, set(a) ^ set(b))
        for k in b:
            close(a[k], b[k], f"{path}.{k}")
    elif isinstance(b, list):
        assert len(a) == len(b), path
        for n, (x, y) in enumerate(zip(a, b)):
            close(x, y, f"{path}[{n}]")
    elif b is None:
        assert a is None, path
    elif isinstance(b, bool):
        assert a is b, path
    elif isinstance(b, (int, float)):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (path, a, b)
    else:
        assert a == b, (path, a, b)


@pytest.mark.parametrize("name", sorted(GOLDEN["cases"]))
def test_matches_hub_formulas(name):
    g = GOLDEN["cases"][name]
    record = {k: v for k, v in g["record"].items() if k != "uw"}
    i = uw.resolve_inputs(record, g["record"]["uw"], GOLDEN["settings"])
    close(i, g["inputs"], "inputs")
    assert uw.missing(i) == g["missing"]
    if g["missing"]:
        return
    c = uw.calc(i)
    close(c, g["calc"], "calc")
    close(uw.checks(i, c, GOLDEN["settings"]), g["checks"], "checks")
    close(uw.project(i), g["project"], "project")
    close(uw.scenarios(i), g["scenarios"], "scenarios")


def test_num_matches_page_parsing():
    assert uw.num("$1,800") == 1800 and uw.num(" 2 400 ") == 2400 and uw.num("") is None and uw.num("abc") is None
    assert uw.num(True) is None and uw.num(0) == 0


def test_settings_ignore_unknown_and_junk():
    st = uw.settings_with_defaults({"planPrivate": "1000", "uwMinCash": "x", "nope": 5})
    assert st["planPrivate"] == 1000 and st["uwMinCash"] == 300 and "nope" not in st


def test_summary_and_csv_shape():
    g = GOLDEN["cases"]["lease_defaults"]
    i = uw.resolve_inputs({k: v for k, v in g["record"].items() if k != "uw"}, {}, GOLDEN["settings"])
    c = uw.calc(i)
    text = uw.summary_text("12 Example St", i, c, uw.checks(i, c, GOLDEN["settings"]), "2026-11-21")
    assert text.startswith("Underwriting: 12 Example St (master lease, 5 beds)") and text.endswith("2026-11-21")
    assert "Targets met: 4 of 4." in text
    rows = uw.csv_rows("12 Example St", i, c)
    assert rows[0] == ["Item", "Value"] and rows[-1][0] == "Upside cash flow / mo" and len(rows) == 18
