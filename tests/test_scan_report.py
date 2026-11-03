import csv
import json

from funders import report, scan
from funders.match import Matcher, load_seeds
from helpers import FakeIRS, make_zip, pf_return, sched_i_return

SEEDS = """
[charity_navigator]
name = "Charity Navigator"
eins = ["13-4148824"]
state = "NJ"
persona = "2"
[candid]
name = "Candid"
aliases = ["Foundation Center"]
state = "NY"
persona = "2"
"""


def run(tmp_path, monkeypatch=None):
    seeds = tmp_path / "seeds.toml"
    seeds.write_text(SEEDS)
    members = {
        "202501_public.xml": pf_return("111111111", "EXAMPLE FAMILY FOUNDATION", "PA",
                                       [("CHARITY NAVIGATOR", "NJ", "GENERAL", 20000), ("CANDID", "NY", "DATA", 30000),
                                        ("PANTRY", "PA", "FOOD", 15000)]),
        "202502_public.xml": sched_i_return("222222222", "EXAMPLE CHARITABLE GIFT FUND", "MA",
                                            [("CHARITY NAVIGATOR INC", "134148824", "NJ", "GENERAL", 10000),
                                             ("CANDID", "", "TX", "SUMMER CAMP", 500)]),
        "202503_public.xml": pf_return("333333333", "UNRELATED FOUNDATION", "OH", [("PANTRY", "OH", "FOOD", 100)]),
    }
    fake = FakeIRS(2025, {"2025_TEOS_XML_01A": make_zip(members)},
                   [("202501", "111111111", "EXAMPLE FAMILY FOUNDATION", "990PF", "202412", "2025_TEOS_XML_01A"),
                    ("202502", "222222222", "EXAMPLE CHARITABLE GIFT FUND", "990", "202406", "2025_TEOS_XML_01A"),
                    ("202503", "333333333", "UNRELATED FOUNDATION", "990PF", "202412", "2025_TEOS_XML_01A")])
    out = tmp_path / "out"
    stats = scan.scan_year(2025, Matcher(load_seeds(seeds)), out, get=fake.get, size_of=fake.size,
                           log=lambda m: None, window=512, pause=0)
    return out, stats, fake


def test_scan_finds_grants_and_resumes(tmp_path):
    out, stats, fake = run(tmp_path)
    assert stats["matched"] == 3 and stats["review"] == 1 and stats["returns"] == 3
    rows = [json.loads(l) for l in (out / "grants.jsonl").read_text().splitlines()]
    assert {r["funder_ein"] for r in rows} == {"111111111", "222222222"}
    assert all(r["source"].endswith("_public.xml") for r in rows)
    # a second run skips the archive already scanned
    stats2 = scan.scan_year(2025, Matcher(load_seeds(tmp_path / "seeds.toml")), out, get=fake.get,
                            size_of=fake.size, log=lambda m: None, pause=0)
    assert stats2["archives"] == 0


def test_report_ranks_and_waits_for_review(tmp_path):
    out, _, _ = run(tmp_path)
    res = report.build(out)
    assert res == {"funders": 2, "grants": 3, "to_review": 1}
    funders = list(csv.DictReader((out / "funders.csv").open()))
    assert funders[0]["funder"] == "EXAMPLE FAMILY FOUNDATION"     # two comparables, PA, open to proposals
    assert funders[0]["persona"] == "1" and funders[0]["accepts_unsolicited"] == "yes"
    assert funders[1]["persona"] == "4"
    sweep = list(csv.DictReader((out / "sweep_import.csv").open()))
    assert sweep[0]["Company"] == "EXAMPLE FAMILY FOUNDATION"

    # a person says yes to the review row: the gift fund now counts two comparables
    rows = list(csv.DictReader((out / "review.csv").open()))
    rows[0]["decision"] = "yes"
    with (out / "review.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    res = report.build(out)
    assert res["to_review"] == 0 and res["grants"] == 4
    gift_fund = [r for r in csv.DictReader((out / "funders.csv").open()) if r["ein"] == "22-2222222"][0]
    assert gift_fund["comparables_funded"] == "2"


def test_large_returns_are_streamed(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "BIG", 100)       # every return counts as large: no quick test, parsed in chunks
    _, stats, _ = run(tmp_path)
    assert stats["matched"] == 3 and stats["parsed"] == 3
