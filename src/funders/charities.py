"""Charities near Mieruka to invite into the pilot, from public IRS data only.

1. The IRS list of exempt organizations in Pennsylvania (Business Master File, eo_pa.csv): every public charity in
   the chosen counties (ZIP code -> county from the Census file), within a revenue band. Private foundations and
   grantmakers are left out: those are funders, and the funder finder covers them.
2. Each charity's latest Form 990, read on its own by byte range (as the funder contacts are): phone, website,
   mission, revenue, contributions, and the officers and key employees it lists, with the officer who signed.
3. A call order, for John only: A, B or C from stated facts (home county, size, how much of its money comes from
   contributions). Charities on the outreach targets list keep the order and notes given there.

The call order is Mieruka's own outreach plan. It is never shown to a charity, never appears in the Mieruka product
and never describes a charity to donors (Mieruka's rule: no ratings).

Writes, in the --out folder:
  charities.csv          one row per charity, in call order, with links to its filing
  charity_contacts.csv   people named on each charity's latest 990 (no home addresses)

    python -m funders charities --out data/charities --targets C:\\Mieruka\\Data\\outreach_targets_charities.csv
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

from funders import contacts, irs, places
from funders.match import norm_ein

BMF = "https://www.irs.gov/pub/irs-soi/eo_{state}.csv"
PRIVATE_FOUNDATION = {"02", "03", "04"}            # BMF FOUNDATION codes for private foundations
SKIP_NTEE = ("T", "Y")                             # grantmakers and mutual-benefit groups: not pilot charities
NTEE_GROUP = {
    "A": "Arts and culture", "B": "Education", "C": "Environment", "D": "Animals", "E": "Health care",
    "F": "Mental health", "G": "Disease and disorders", "H": "Medical research", "I": "Crime and legal",
    "J": "Employment", "K": "Food and nutrition", "L": "Housing and shelter", "M": "Disaster relief and safety",
    "N": "Recreation and sports", "O": "Youth development", "P": "Human services", "Q": "International",
    "R": "Civil rights and advocacy", "S": "Community improvement", "T": "Philanthropy and grantmaking",
    "U": "Science and technology", "V": "Social science", "W": "Public benefit", "X": "Religion-related",
    "Y": "Mutual benefit", "Z": "Unclassified"}
YEARS = (2026, 2025, 2024)
MIN_REV, MAX_REV = 500_000, 50_000_000
TOP = 400
MAX_PEOPLE = 8

FIELDS = ["call_order", "call_order_why", "charity", "ein", "city", "zip", "county", "cause", "ntee", "revenue",
          "contributions", "contributions_share", "restricted_net_assets", "expenses", "tax_year", "phone", "website", "mission",
          "on_targets_list", "why", "angle", "filing", "propublica"]
PEOPLE = ["ein", "charity", "kind", "name", "title", "phone", "email", "notes", "tax_year", "source"]


def _num(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def fmt_ein(e: str) -> str:
    e = norm_ein(e)
    return f"{e[:2]}-{e[2:]}" if len(e) == 9 else e


def money(n) -> str:
    if n is None:
        return ""
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}K"


def read_bmf(data: bytes | str, zip_county: dict[str, str], min_rev: int = MIN_REV, max_rev: int = MAX_REV,
             keep: set[str] = frozenset()) -> list[dict]:
    """Public charities in the wanted counties and revenue band (always keeping the EINs in keep)."""
    text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else data
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
        ein = norm_ein(r.get("EIN", ""))
        z = r.get("ZIP", "")[:5]
        county = zip_county.get(z)
        rev = _num(r.get("REVENUE_AMT")) or _num(r.get("INCOME_AMT")) or 0
        listed = ein in keep
        if not listed:
            if r.get("SUBSECTION") != "03" or r.get("FOUNDATION") in PRIVATE_FOUNDATION or not county:
                continue
            if (r.get("NTEE_CD") or "Z")[:1].upper() in SKIP_NTEE or not (min_rev <= rev <= max_rev):
                continue
        ntee = (r.get("NTEE_CD") or "").upper()
        out.append({"ein": ein, "charity": r.get("NAME", ""), "city": r.get("CITY", "").title(), "zip": z,
                    "county_fips": county or "", "ntee": ntee, "cause": NTEE_GROUP.get(ntee[:1], ""),
                    "bmf_revenue": rev, "tax_period": r.get("TAX_PERIOD", "")})
    return out


def latest_filings(eins: set[str], folder: Path, years=YEARS, get=irs.http_range, log=print) -> dict[str, dict]:
    """Each EIN's most recent Form 990 in the IRS e-file indexes: {ein: {year, object_id, batch, tax_period}}.
    The rows for these EINs are kept in folder/cache so the large indexes are read once a month."""
    best: dict[str, dict] = {}
    cache = Path(folder) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for year in years:
        saved = cache / f"index_{year}_rows.json"
        rows = None
        if saved.exists() and time.time() - saved.stat().st_mtime < places.CACHE_DAYS * 86400:
            rows = json.loads(saved.read_text())
            if not set(eins) <= set(rows.get("_eins", [])):
                rows = None
        if rows is None:
            try:
                data = get(irs.INDEX.format(year=year), None, None)
            except urllib.error.HTTPError as ex:
                log(f"  no {year} index ({ex.code}); skipped")
                continue
            log(f"  read the {year} e-file index")
            rows = {"_eins": sorted(eins)}
            reader = csv.reader(io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace", newline=""))
            head = [h.strip().upper() for h in next(reader, [])]
            ix = {h: i for i, h in enumerate(head)}
            for r in reader:
                if len(r) <= ix.get("OBJECT_ID", 99):
                    continue
                e = norm_ein(r[ix["EIN"]])
                rt = r[ix["RETURN_TYPE"]].strip().upper().replace("-", "")
                if e in eins and rt in ("990", "990EZ"):
                    rows.setdefault(e, []).append({"object_id": r[ix["OBJECT_ID"]].strip(), "tax_period": r[ix["TAX_PERIOD"]].strip(),
                                                   "batch": r[ix["XML_BATCH_ID"]].strip() if "XML_BATCH_ID" in ix and len(r) > ix["XML_BATCH_ID"] else "",
                                                   "type": rt})
            saved.write_text(json.dumps(rows))
        for e, found in rows.items():
            if e == "_eins" or e not in eins:
                continue
            for f in found:
                cand = {**f, "year": year}
                key = (f["type"] == "990", f["tax_period"], f["object_id"])
                if e not in best or key > (best[e]["type"] == "990", best[e]["tax_period"], best[e]["object_id"]):
                    best[e] = cand
    return best


def locate(filings: dict[str, dict], arcs: "contacts._Archives", get=irs.http_range, log=print) -> dict[str, str]:
    """Where each return sits: {ein: 'archive url#objectid_public.xml'}. Uses the index's batch name when it gives
    one; otherwise looks through that year's archive tables of contents (read once each)."""
    out, missing = {}, {}
    for e, f in filings.items():
        name = f"{f['object_id']}_public.xml"
        if f.get("batch"):
            out[e] = irs.ZIP.format(year=f["year"], batch=f["batch"]) + "#" + name
        else:
            missing.setdefault(f["year"], {})[name] = e
    for year, want in missing.items():
        try:
            zips = irs.published_zips(year, get)
        except (urllib.error.URLError, OSError):
            zips = []
        for z in zips:
            if not want:
                break
            url = irs.ZIP.format(year=year, batch=z)
            try:
                names = arcs.directory(url)
            except (urllib.error.URLError, OSError) as ex:
                log(f"  can't read {z}: {ex}")
                continue
            for name in list(want):
                if name in names:
                    out[want.pop(name)] = url + "#" + name
    return out


def pick_people(c: dict) -> list[dict]:
    """The people worth knowing at a charity: its executive, development and board leads first."""
    def rank(o):
        t = (o.get("title") or "").lower()
        if re.search(r"executive director|\bceo\b|chief executive|president", t) and "vice" not in t:
            return 0
        if re.search(r"development|advancement|philanthrop|fundrais|donor", t):
            return 1
        if "chair" in t:
            return 2
        return 3 if o.get("officer") else 4
    seen, people = set(), []
    for o in sorted(c["officers"], key=rank):
        if o["name"] and o["name"].lower() not in seen:
            seen.add(o["name"].lower())
            people.append(o)
    return people[:MAX_PEOPLE]


def call_order(r: dict, county: str) -> tuple[str, str]:
    """A, B or C from stated facts; never a judgment of the charity's work."""
    rev, share = r.get("revenue") or r.get("bmf_revenue") or 0, r.get("contributions_share")
    facts = [f"{county} County" if county else "outside the chosen counties", f"revenue {money(rev)}"]
    if share is not None:
        facts.append(f"{share:.0%} of revenue from contributions")
    if r.get("restricted_net_assets"):
        facts.append(f"holds {money(r['restricted_net_assets'])} in donor-restricted gifts")
    home = county in places.HOME
    if home and 1_000_000 <= rev <= 25_000_000 and (share or 0) >= 0.35:
        letter = "A"
    elif county and (share or 0) >= 0.15:
        letter = "B"
    else:
        letter = "C"
    return letter, "; ".join(facts)


def load_targets(path) -> dict[str, dict]:
    """The outreach targets list (charities), by EIN: its call order and notes win over the computed ones."""
    if not path or not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {norm_ein(r["ein"]): r for r in csv.DictReader(f) if r.get("ein")}


def build(out_dir, targets: str | None = None, counties=tuple(places.COUNTIES), min_rev: int = MIN_REV,
          max_rev: int = MAX_REV, top: int = TOP, years=YEARS, get=irs.http_range, size_of=irs.http_size,
          pause: float = irs.PAUSE, log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fips = {places.COUNTIES[c] for c in counties}
    names = places.county_names()
    tlist = load_targets(targets)
    zc = places.zip_to_county(places.cached(places.ZCTA_COUNTY, out, get, log=log), fips)
    found = read_bmf(places.cached(BMF.format(state="pa"), out, get, log=log), zc, min_rev, max_rev, set(tlist))
    log(f"{len(found)} public charities in {', '.join(counties)} with revenue {money(min_rev)}–{money(max_rev)}"
        + (f" (plus the {len(tlist)} on the targets list)" if tlist else ""))

    def before(r):          # which 990s to read first: the targets list, home counties, mid-size
        county = names.get(r["county_fips"], "")
        return (r["ein"] not in tlist, county not in places.HOME, not (1_000_000 <= r["bmf_revenue"] <= 25_000_000),
                -r["bmf_revenue"])
    found.sort(key=before)
    chosen = found[:max(top, len(tlist))]
    filings = latest_filings({r["ein"] for r in chosen}, out, years, get, log)
    arcs = contacts._Archives(get, size_of, pause)
    where = locate(filings, arcs, get, log)
    rows, people, unread = [], [], []
    for i, r in enumerate(chosen, 1):
        county = names.get(r["county_fips"], "")
        src = where.get(r["ein"])
        c = None
        if src:
            try:
                c = contacts.read_contacts(arcs.chunks(src))
            except (urllib.error.URLError, OSError, KeyError, ValueError, ET.ParseError) as ex:
                log(f"  can't read {r['charity']}: {ex}")
        if c is None:
            unread.append(r["charity"])
        f = (c or {}).get("facts", {})
        rev, gifts = _num(f.get("CYTotalRevenueAmt")), _num(f.get("CYContributionsGrantsAmt"))
        row = {**r, "county": county, "revenue": rev if rev is not None else r["bmf_revenue"], "contributions": gifts,
               "contributions_share": (gifts / rev) if rev and gifts is not None and rev > 0 else None,
               "restricted_net_assets": _num(f.get("RestrictedNetAssetsEOY")),
               "expenses": _num(f.get("CYTotalExpensesAmt")), "tax_year": (c or {}).get("tax_year", ""),
               "phone": (c or {}).get("phone", ""), "website": (c or {}).get("website", ""),
               "mission": (f.get("ActivityOrMissionDesc") or f.get("MissionDesc") or "")[:400],
               "filing": src or "", "propublica": f"https://projects.propublica.org/nonprofits/organizations/{r['ein']}"}
        letter, why = call_order(row, county)
        t = tlist.get(r["ein"])
        row.update({"call_order": (t.get("priority") or letter) if t else letter, "call_order_why": why,
                    "on_targets_list": "yes" if t else "", "why": (t or {}).get("why", ""), "angle": (t or {}).get("angle", "")})
        rows.append(row)
        if c:
            base = {"ein": fmt_ein(r["ein"]), "charity": r["charity"], "tax_year": c["tax_year"], "source": src}
            named = set()
            s = c["signer"]
            if s and s["name"]:
                named.add(s["name"].lower())
                people.append({**base, "kind": "signer", "name": s["name"], "title": s["title"], "phone": s["phone"],
                               "email": s["email"], "notes": "Officer who signed the charity's return."})
            for o in pick_people(c):
                if o["name"].lower() in named:
                    continue
                people.append({**base, "kind": "officer", "name": o["name"], "title": o["title"], "phone": "", "email": "",
                               "notes": "Listed on the charity's 990 (Part VII) as an officer, director, trustee or key employee."})
        if i % 50 == 0:
            log(f"  {i} of {len(chosen)} charities read")
    rows.sort(key=lambda x: (x["call_order"], x["county"] not in places.HOME, -(x["revenue"] or 0)))
    with (out / "charities.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for x in rows:
            w.writerow({**x, "ein": fmt_ein(x["ein"]),
                        "contributions_share": "" if x["contributions_share"] is None else f"{x['contributions_share']:.2f}"})
    with (out / "charity_contacts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PEOPLE)
        w.writeheader()
        w.writerows(people)
    res = {"found": len(found), "charities": len(rows), "read": len(rows) - len(unread), "people": len(people),
           "by_order": {k: sum(1 for x in rows if x["call_order"] == k) for k in "ABC"}, "unread": unread}
    log(f"{res['charities']} charities written ({res['read']} with their latest 990 read): "
        f"A {res['by_order']['A']}, B {res['by_order']['B']}, C {res['by_order']['C']}; {res['people']} people"
        + (f"; no 990 read for {len(unread)}" if unread else ""))
    return res
