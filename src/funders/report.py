"""Turn scan results into a ranked funder prospect list.

  review.csv          uncertain matches; write yes or no in the "decision" column, then run again
  funders.csv         every funder of a comparable organization, highest priority first
  sweep_import.csv    the top prospects, as leads for the Sweep Console
  recipient_eins.txt  tax IDs recipients filed under each comparable's name, to confirm in seeds.toml

Priority (0 to 100) follows the playbook: breadth 30, recency 20, size fit 20, geography 15,
openness 15. It ranks funders for Mieruka's own fundraising; it never describes a charity to donors.
"""
from __future__ import annotations

import csv
import json
import tomllib
from collections import defaultdict
from pathlib import Path

from funders.match import norm_ein, norm_name

REVIEW_FIELDS = ["decision", "seed_name", "reason", "recipient", "recipient_ein", "recipient_state", "amount",
                 "purpose", "funder_name", "funder_ein", "tax_year", "source"]

DAF_OR_WEALTH = ("CHARITABLE GIFT FUND", "CHARITABLE ENDOWMENT PROGRAM", "SCHWAB CHARITABLE", "GLOBAL IMPACT FUNDING",
                 "DONOR ADVISED", "NATIONAL PHILANTHROPIC TRUST", "AYCO", "AMERICAN ENDOWMENT FOUNDATION",
                 "RENAISSANCE CHARITABLE", "GOLDMAN SACHS PHILANTHROPY", "MORGAN STANLEY", "JPMORGAN", "MERRILL",
                 "RAYMOND JAMES", "EDWARD JONES", "UBS ", "BNY MELLON", "NORTHERN TRUST", "WELLS FARGO",
                 "BANK OF AMERICA", "CHARLES SCHWAB", "FIDELITY", "VANGUARD", "T ROWE PRICE", "PNC ")
CORPORATE = ("GOOGLE", "TWILIO", "SALESFORCE", "DELL ", "HEWLETT PACKARD", "OKTA", "SERVICENOW", "BLACKROCK",
             "MICROSOFT", "CISCO", "INTEL ", "ORACLE", "ADOBE", "IBM ", "AMAZON", "META PLATFORMS", "COMCAST",
             "CORPORATE", "COMPANY FOUNDATION", "CORPORATION FOUNDATION")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _grant_key(r: dict) -> tuple:
    return (norm_ein(r["funder_ein"]), r["tax_year"], norm_name(r["recipient"]), round(float(r["amount"] or 0)),
            (r["purpose"] or "").upper().strip())


def _read_decisions(path: Path) -> dict[tuple, str]:
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            out[(row["source"], norm_name(row["recipient"]), str(row["amount"]))] = (row.get("decision") or "").strip().lower()
    return out


def persona_for(name: str, state: str, return_type: str, total_paid: float, overrides: dict[str, str], ein: str) -> str:
    if ein in overrides:
        return overrides[ein]
    n = f" {norm_name(name)} "
    if any(f" {k.strip()} " in n or k in n for k in DAF_OR_WEALTH):
        return "4"
    if any(f" {k.strip()} " in n for k in CORPORATE):
        return "3"
    if state == "PA":
        return "1"
    if return_type == "990PF" and total_paid >= 25_000_000:
        return "2"
    return ""      # a person decides (2 or 5)


def priority_parts(f: dict) -> dict[str, int]:
    breadth = round(30 * min(len(f["seeds"]), 4) / 4)
    y = max((int(t) for t in f["years"] if str(t).isdigit()), default=0)
    recency = 20 if y >= 2024 else 14 if y == 2023 else 8 if y == 2022 else 3
    med = f.get("median_grant")
    size = 0 if med is None else 20 if 10_000 <= med <= 250_000 else 10 if 5_000 <= med <= 1_000_000 else 0
    geo = 15 if f["state"] == "PA" else 15 if f.get("recipient_states", 0) >= 5 else 5
    pre = f.get("preselected_only")
    openness = 8 if pre is None else 0 if pre else 15
    return {"breadth": breadth, "recency": recency, "size": size, "geography": geo, "openness": openness}


def build(out_dir: str | Path, overrides_path: str | Path | None = None, top: int = 100) -> dict:
    out = Path(out_dir)
    grants = _read_jsonl(out / "grants.jsonl")
    returns = _read_jsonl(out / "funders.jsonl")
    overrides = {}
    if overrides_path and Path(overrides_path).exists():
        overrides = {norm_ein(k): str(v) for k, v in tomllib.loads(Path(overrides_path).read_text()).get("persona", {}).items()}

    # one copy of each grant (a rerun or an amended return can repeat one)
    seen, unique = set(), []
    for r in grants:
        k = _grant_key(r)
        if k not in seen:
            seen.add(k)
            unique.append(r)

    # review list: keep earlier decisions, add new rows
    review_path = out / "review.csv"
    decisions = _read_decisions(review_path)
    review_rows, accepted = [], []
    for r in unique:
        if r["status"] == "matched":
            accepted.append(r)
            continue
        d = decisions.get((r["source"], norm_name(r["recipient"]), str(r["amount"])), "")
        if d in {"yes", "y"}:
            accepted.append(r)
        review_rows.append({**{k: r.get(k, "") for k in REVIEW_FIELDS}, "decision": d})
    with review_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows(sorted(review_rows, key=lambda x: (x["decision"] != "", x["seed_name"], -float(x["amount"] or 0))))

    # latest return per funder, for overall giving facts
    latest = {}
    for r in returns:
        e = norm_ein(r["funder_ein"])
        if e not in latest or (r.get("tax_period_end") or "") > (latest[e].get("tax_period_end") or ""):
            latest[e] = r

    fund = defaultdict(lambda: {"seeds": set(), "grants": [], "years": set(), "sources": set()})
    for r in accepted:
        e = norm_ein(r["funder_ein"])
        f = fund[e]
        f["seeds"].add(r["seed_name"])
        f["grants"].append(r)
        f["years"].add(r["tax_year"])
        f["sources"].add(r["source"])
        f["name"] = r["funder_name"]

    rows = []
    for e, f in fund.items():
        lr = latest.get(e, {})
        f.update(state=lr.get("funder_state", ""), median_grant=lr.get("median_grant"),
                 preselected_only=lr.get("preselected_only"), recipient_states=lr.get("recipient_states", 0))
        parts = priority_parts(f)
        total = sum(float(g["amount"] or 0) for g in f["grants"])
        biggest = max(f["grants"], key=lambda g: float(g["amount"] or 0))
        pre = lr.get("preselected_only")
        rows.append({
            "priority": sum(parts.values()),
            "funder": f["name"], "ein": f"{e[:2]}-{e[2:]}", "state": f["state"],
            "persona": persona_for(f["name"], f["state"], lr.get("return_type", ""), lr.get("total_paid") or 0, overrides, e),
            "comparables_funded": len(f["seeds"]), "comparables": "; ".join(sorted(f["seeds"])),
            "total_to_comparables": round(total), "largest_grant": round(float(biggest["amount"] or 0)),
            "largest_grant_to": biggest["seed_name"], "latest_year": max(f["years"]),
            "median_grant_overall": None if f["median_grant"] is None else round(f["median_grant"]),
            "total_grants_paid": round(lr.get("total_paid") or 0),
            "accepts_unsolicited": "" if pre is None else "no" if pre else "yes",
            "priority_breakdown": " ".join(f"{k} {v}" for k, v in parts.items()),
            "filings": " ".join(sorted(f["sources"])),
            "profile": f"https://projects.propublica.org/nonprofits/organizations/{e}",
        })
    rows.sort(key=lambda r: (-r["priority"], -r["total_to_comparables"]))
    if rows:
        with (out / "funders.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with (out / "sweep_import.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Company", "State", "Persona", "Priority", "Notes", "Source"])
            for r in rows[:top]:
                note = (f"Funded {r['comparables']} (${r['total_to_comparables']:,} total, latest {r['latest_year']}). "
                        f"Median grant {('$' + format(r['median_grant_overall'], ',')) if r['median_grant_overall'] else 'unknown'}; "
                        f"accepts unsolicited: {r['accepts_unsolicited'] or 'n/a (public charity)'}.")
                w.writerow([r["funder"], r["state"], r["persona"] or "decide", r["priority"], note, r["profile"]])

    # tax IDs filed under each comparable's name, for confirming seeds.toml
    seen_eins = defaultdict(lambda: defaultdict(int))
    for r in unique:
        if r.get("recipient_ein"):
            seen_eins[r["seed_name"]][norm_ein(r["recipient_ein"])] += 1
    with (out / "recipient_eins.txt").open("w") as fh:
        for seed, eins in sorted(seen_eins.items()):
            fh.write(f"{seed}: " + ", ".join(f"{e[:2]}-{e[2:]} ({n} grants)" for e, n in
                                               sorted(eins.items(), key=lambda x: -x[1])) + "\n")
    return {"funders": len(rows), "grants": len(accepted), "to_review": sum(1 for r in review_rows if not r["decision"])}
