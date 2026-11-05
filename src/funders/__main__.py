"""Funder finder.

    python -m funders scan --years 2023 2024 2025 --out data/funders
    python -m funders scan --years 2025 --max-zips 1 --out data/trial      # a quick trial on one archive
    python -m funders report --out data/funders
    python -m funders contacts --out data/funders --top 250   # grants contacts, officers, phone, website
    python -m funders charities --out data/charities --targets outreach_targets_charities.csv
    python -m funders advisors --sec-file data/advisors --out data/advisors --targets outreach_targets_advisors.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

from funders import advisors, charities, contacts, places, report, scan
from funders.match import Matcher, load_seeds

ROOT = Path(__file__).resolve().parents[2]


def limit_memory(mb: int):
    """Ask the system to refuse memory past this ceiling. Python then raises MemoryError for the one
    return that needs too much, which the scan records and skips, instead of the whole run being killed."""
    try:
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (mb * 2**20, hard))
    except (ImportError, ValueError, OSError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="funders", description="Find funders of organizations like Mieruka")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="read IRS archives for grants to the comparable organizations")
    s.add_argument("--years", nargs="+", type=int, required=True, help="IRS publication years, e.g. 2023 2024 2025")
    s.add_argument("--out", required=True)
    s.add_argument("--seeds", default=str(ROOT / "config" / "seeds.toml"))
    s.add_argument("--max-zips", type=int, help="stop after this many archives per year (for a trial)")
    s.add_argument("--max-memory-mb", type=int, default=1000,
                   help="memory ceiling; a return needing more is skipped and listed, the run goes on (default 1000)")
    r = sub.add_parser("report", help="build the ranked funder list from scan results")
    r.add_argument("--out", required=True)
    r.add_argument("--overrides", default=str(ROOT / "config" / "personas.toml"))
    r.add_argument("--top", type=int, default=100)
    r.add_argument("--seeds", default=str(ROOT / "config" / "seeds.toml"))
    c = sub.add_parser("contacts", help="who to contact at each top funder, from its latest filing")
    c.add_argument("--out", required=True)
    c.add_argument("--top", type=int, default=250)
    ch = sub.add_parser("charities", help="charities near Mieruka to invite into the pilot, from IRS data")
    ch.add_argument("--out", required=True)
    ch.add_argument("--targets", help="the outreach targets list (charities) as CSV; its order and notes are kept")
    ch.add_argument("--counties", nargs="+", default=list(places.COUNTIES), choices=list(places.COUNTIES))
    ch.add_argument("--min-revenue", type=int, default=charities.MIN_REV)
    ch.add_argument("--max-revenue", type=int, default=charities.MAX_REV)
    ch.add_argument("--top", type=int, default=charities.TOP, help="how many charities' 990s to read (default 400)")
    ad = sub.add_parser("advisors", help="advisors near Mieruka, from the SEC's list of registered advisers")
    ad.add_argument("--sec-file", required=True, help="the SEC's monthly ZIP (or the folder it was saved in: newest ia*.zip)")
    ad.add_argument("--out", required=True)
    ad.add_argument("--targets", help="the outreach targets list (advisors) as CSV; its order and notes are kept")
    ad.add_argument("--counties", nargs="+", default=list(places.COUNTIES), choices=list(places.COUNTIES))
    a = ap.parse_args(argv)

    if a.cmd == "charities":
        charities.build(a.out, a.targets, a.counties, a.min_revenue, a.max_revenue, a.top)
    elif a.cmd == "advisors":
        f = Path(a.sec_file)
        if f.is_dir():
            found = sorted([*f.glob("ia*.zip"), *f.glob("ia*.xlsx"), *f.glob("ia*.csv")], key=lambda p: p.stat().st_mtime)
            found = [p for p in found if "exempt" not in p.name.lower()] or found
            if not found:
                raise SystemExit(f"No SEC file (ia*.zip or ia*.xlsx) in {f}. Download the latest 'Registered Investment Advisers' "
                                 "ZIP from sec.gov into that folder first.")
            f = found[-1]
        advisors.build(f, a.out, a.targets, a.counties)
    elif a.cmd == "contacts":
        contacts.build(a.out, a.top)
    elif a.cmd == "scan":
        limit_memory(a.max_memory_mb)
        scan.scan(a.years, Matcher(load_seeds(a.seeds)), a.out, max_zips=a.max_zips)
    else:
        res = report.build(a.out, a.overrides, a.top, a.seeds)
        print(f"{res['funders']} funders from {res['grants']} grants; {res['to_review']} grants waiting for review "
              f"in {Path(a.out) / 'review.csv'}")


if __name__ == "__main__":
    main()
