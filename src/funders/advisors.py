"""Advisors near Mieruka, from the SEC's public list of registered investment advisers (Form ADV Part 1A).

The SEC posts the list once a month as a ZIP on sec.gov ("Information About Registered Investment Advisers and
Exempt Reporting Advisers", the Registered Investment Advisers file). The SEC asks automated downloads to identify
themselves with a contact address, so this tool doesn't fetch it: download it in a browser and pass its path.

Kept for each firm whose main office is in the chosen counties: name, address, phone, website, assets under
management (Item 5.F), employees (5.A), how many high-net-worth individuals and charitable organizations it serves
(5.D), its latest filing date, and its compliance officer when the file names one. Firms registered only with the
state (most small ones) aren't in the SEC's list; the outreach targets list and John's own network cover those.

A call order (A, B, C) from those stated facts, for John only. Firms on the outreach targets list keep the order and
notes given there; list firms not found in the SEC file are kept as they are.

Writes, in the --out folder:
  advisors.csv          one row per firm, in call order, with its SEC number and a link to its public record
  advisor_contacts.csv  the compliance officer each firm names (when the file has it)

    python -m funders advisors --sec-file C:\\Mieruka\\Data\\advisors\\ia100226.zip --out data/advisors
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from funders import irs, places
from funders.match import norm_name

FIELDS = ["call_order", "call_order_why", "firm", "legal_name", "crd", "sec_number", "city", "zip", "county", "phone",
          "website", "aum", "employees", "hnw_clients", "charity_clients", "individual_clients", "latest_filing",
          "on_targets_list", "persona", "firm_type", "why", "angle", "list_source", "iapd"]
PEOPLE = ["crd", "firm", "kind", "name", "title", "phone", "email", "notes", "source"]

# what to look for in the SEC file's column names (lower case, spaces squeezed)
COLUMNS = {
    "crd": [r"organization crd", r"\bcrd\b"], "sec_number": [r"^sec#", r"sec number", r"sec#"],
    "firm": [r"primary business name"], "legal_name": [r"^legal name"],
    "street": [r"main office street address 1"], "city": [r"main office city"], "state": [r"main office state"],
    "zip": [r"main office postal code", r"main office zip"], "phone": [r"main office telephone"],
    "website": [r"website address", r"^website"], "aum": [r"5f\(2\)\(c\)"], "employees": [r"^5a\b", r"^5a$"],
    "individual_clients": [r"5d\(a\)\(1\)"], "hnw_clients": [r"5d\(b\)\(1\)"], "charity_clients": [r"5d\(h\)\(1\)"],
    "latest_filing": [r"latest adv filing date"],
    "cco_name": [r"chief compliance officer.*name", r"^cco name"], "cco_phone": [r"chief compliance officer.*(telephone|phone)"],
    "cco_email": [r"chief compliance officer.*e-?mail"],
}


def _key(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def find_columns(header: list[str]) -> dict[str, int]:
    keys = [_key(h) for h in header]
    out = {}
    for field, pats in COLUMNS.items():
        for p in pats:
            hit = next((i for i, k in enumerate(keys) if re.search(p, k)), None)
            if hit is not None:
                out[field] = hit
                break
    return out


def _rows_from_xlsx(data: bytes):
    import openpyxl                                  # only needed when the SEC file is a spreadsheet
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for row in wb.worksheets[0].iter_rows(values_only=True):
        yield ["" if v is None else str(v) for v in row]


def read_sec_file(path) -> tuple[list[str], list[list[str]]]:
    """The header and rows of the SEC's file: a ZIP holding a .csv or .xlsx, or the .csv/.xlsx itself."""
    p = Path(path)
    data, name = p.read_bytes(), p.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = [n for n in z.namelist() if n.lower().endswith((".csv", ".xlsx", ".txt"))]
            if not inner:
                raise ValueError(f"No .csv or .xlsx inside {p.name}")
            inner.sort(key=lambda n: ("exempt" in n.lower(), n))      # the registered advisers' file, not the exempt one
            name = inner[0].lower()
            data = z.read(inner[0])
    if name.endswith(".xlsx"):
        rows = list(_rows_from_xlsx(data))
    else:
        text = data.decode("utf-8-sig", "replace") if b"\x00" not in data[:2000] else data.decode("utf-16", "replace")
        rows = list(csv.reader(io.StringIO(text), delimiter="\t" if text.count("\t") > text.count(",") else ","))
    if not rows:
        raise ValueError(f"{p.name} is empty")
    return rows[0], rows[1:]


def _num(v) -> int | None:
    v = re.sub(r"[^\d.]", "", str(v or ""))
    try:
        return int(float(v)) if v else None
    except ValueError:
        return None


def money(n) -> str:
    if not n:
        return ""
    return f"${n / 1e9:.1f}B" if n >= 1e9 else f"${round(n / 1e6)}M"


def call_order(r: dict) -> tuple[str, str]:
    """A, B or C from what the firm reports; John's own order of who to call first."""
    county, aum, hnw, ch = r.get("county", ""), r.get("aum") or 0, r.get("hnw_clients") or 0, r.get("charity_clients") or 0
    facts = [f"{county} County" if county else "outside the chosen counties"]
    if aum:
        facts.append(f"{money(aum)} under management")
    if r.get("hnw_clients") is not None:
        facts.append(f"{hnw} high-net-worth clients")
    if ch:
        facts.append(f"{ch} charitable-organization clients")
    if county in places.HOME and hnw >= 25 and 100_000_000 <= aum <= 5_000_000_000:
        letter = "A"
    elif county and hnw >= 10:
        letter = "B"
    else:
        letter = "C"
    return letter, "; ".join(facts)


def load_targets(path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("firm")]


def _site(v: str) -> str:
    v = (v or "").strip()
    return "" if v.lower() in ("", "n/a", "none") else re.sub(r"^https?://", "", v, flags=re.I).rstrip("/").lower()


def build(sec_file, out_dir, targets: str | None = None, counties=tuple(places.COUNTIES), get=irs.http_range,
          log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fips = {places.COUNTIES[c] for c in counties}
    names = places.county_names()
    zc = places.zip_to_county(places.cached(places.ZCTA_COUNTY, out, get, log=log), fips)
    header, rows = read_sec_file(sec_file)
    col = find_columns(header)
    missing = [k for k in ("crd", "firm", "state", "zip") if k not in col]
    if missing:
        raise ValueError(f"The SEC file's columns weren't recognised (missing {', '.join(missing)}). "
                         f"First columns: {', '.join(header[:12])}")
    log(f"SEC file: {len(rows):,} advisers; columns found: {', '.join(sorted(col))}")
    lacking = [k for k in ("aum", "hnw_clients", "charity_clients") if k not in col]
    if lacking:
        log(f"  note: this SEC file has no {', '.join(lacking)} columns, so call order uses what it does have. "
            "Send Claude the first line of the file to fix the column names.")
    tlist = load_targets(targets)
    by_name = {norm_name(t["firm"]): t for t in tlist}
    firms, people, matched = [], [], set()

    def v(r, k):
        i = col.get(k)
        return (r[i] if i is not None and i < len(r) else "").strip()
    for r in rows:
        if v(r, "state").upper() not in ("PA", "PENNSYLVANIA"):
            continue
        sec_no = v(r, "sec_number")
        if sec_no.startswith("802-"):
            continue                                  # exempt reporting advisers (private fund managers)
        county = names.get(zc.get(v(r, "zip")[:5], ""), "")
        if not county:
            continue
        f = {"firm": v(r, "firm") or v(r, "legal_name"), "legal_name": v(r, "legal_name"), "crd": v(r, "crd"),
             "sec_number": sec_no, "city": v(r, "city").title(), "zip": v(r, "zip")[:5], "county": county,
             "phone": v(r, "phone"), "website": _site(v(r, "website")), "aum": _num(v(r, "aum")),
             "employees": _num(v(r, "employees")), "hnw_clients": _num(v(r, "hnw_clients")),
             "charity_clients": _num(v(r, "charity_clients")), "individual_clients": _num(v(r, "individual_clients")),
             "latest_filing": v(r, "latest_filing"), "list_source": "SEC Form ADV",
             "iapd": f"https://adviserinfo.sec.gov/firm/summary/{v(r, 'crd')}"}
        letter, why = call_order(f)
        t = by_name.get(norm_name(f["firm"])) or by_name.get(norm_name(f["legal_name"]))
        if t:
            matched.add(norm_name(t["firm"]))
        f.update({"call_order": (t.get("priority") or letter) if t else letter, "call_order_why": why,
                  "on_targets_list": "yes" if t else "", "persona": (t or {}).get("persona", ""),
                  "firm_type": (t or {}).get("type", ""), "why": (t or {}).get("why", ""), "angle": (t or {}).get("angle", "")})
        firms.append(f)
        if v(r, "cco_name"):
            people.append({"crd": f["crd"], "firm": f["firm"], "kind": "compliance officer", "name": v(r, "cco_name").title(),
                           "title": "Chief Compliance Officer", "phone": v(r, "cco_phone"), "email": v(r, "cco_email"),
                           "notes": "Named in the firm's Form ADV (Item 1.J).", "source": f["iapd"]})
    for t in tlist:                                   # list firms the SEC file doesn't have (state-registered, branch offices)
        if norm_name(t["firm"]) in matched:
            continue
        firms.append({"firm": t["firm"], "city": t.get("city", ""), "county": (t.get("area") or "").split("/")[0],
                      "call_order": t.get("priority") or "B", "call_order_why": "From the outreach targets list",
                      "on_targets_list": "yes", "persona": t.get("persona", ""), "firm_type": t.get("type", ""),
                      "why": t.get("why", ""), "angle": t.get("angle", ""), "list_source": t.get("src", "Outreach targets list"),
                      "iapd": t.get("url", "")})
    firms.sort(key=lambda x: (x["call_order"], x.get("county") not in places.HOME, -(x.get("aum") or 0)))
    with (out / "advisors.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(firms)
    with (out / "advisor_contacts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PEOPLE)
        w.writeheader()
        w.writerows(people)
    res = {"firms": len(firms), "from_sec": len(firms) - (len(tlist) - len(matched)), "list_matched": len(matched),
           "list_only": len(tlist) - len(matched), "people": len(people),
           "by_order": {k: sum(1 for x in firms if x["call_order"] == k) for k in "ABC"}}
    log(f"{res['firms']} advisory firms written ({res['from_sec']} from the SEC file, {res['list_only']} from the targets "
        f"list only): A {res['by_order']['A']}, B {res['by_order']['B']}, C {res['by_order']['C']}; "
        f"{res['people']} compliance officers named")
    return res
