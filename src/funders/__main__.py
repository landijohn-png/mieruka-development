"""Funder finder.

    python -m funders scan --years 2023 2024 2025 --out data/funders
    python -m funders scan --years 2025 --max-zips 1 --out data/trial      # a quick trial on one archive
    python -m funders report --out data/funders
"""
from __future__ import annotations

import argparse
from pathlib import Path

from funders import report, scan
from funders.match import Matcher, load_seeds

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="funders", description="Find funders of organizations like Mieruka")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="read IRS archives for grants to the comparable organizations")
    s.add_argument("--years", nargs="+", type=int, required=True, help="IRS publication years, e.g. 2023 2024 2025")
    s.add_argument("--out", required=True)
    s.add_argument("--seeds", default=str(ROOT / "config" / "seeds.toml"))
    s.add_argument("--max-zips", type=int, help="stop after this many archives per year (for a trial)")
    r = sub.add_parser("report", help="build the ranked funder list from scan results")
    r.add_argument("--out", required=True)
    r.add_argument("--overrides", default=str(ROOT / "config" / "personas.toml"))
    r.add_argument("--top", type=int, default=100)
    a = ap.parse_args(argv)

    if a.cmd == "scan":
        scan.scan(a.years, Matcher(load_seeds(a.seeds)), a.out, max_zips=a.max_zips)
    else:
        res = report.build(a.out, a.overrides, a.top)
        print(f"{res['funders']} funders from {res['grants']} grants; {res['to_review']} grants waiting for review "
              f"in {Path(a.out) / 'review.csv'}")


if __name__ == "__main__":
    main()
