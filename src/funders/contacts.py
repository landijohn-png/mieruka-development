"""Who to contact at each funder, from the funder's own latest IRS filing.

For each top funder in funders.csv this reads its most recent return (only that file, by range requests) and takes:
  - the grants contact a private foundation names in Form 990-PF Part XV line 2a: person, mailing address, phone,
    email, what to submit, deadlines and restrictions (or that it funds only pre-selected organizations);
  - its officers, directors, trustees and key employees, with titles (990-PF Part VIII, Form 990 Part VII);
  - the officer who signed the return, the organization's phone and its website.

Officers' own addresses are not kept: small foundations often file with a trustee's home address. Only the address the
foundation gives for grant requests is kept.

Writes, in the --out folder:
  contacts.csv      one row per person: ein, funder, kind, name, title, phone, email, address, notes, source
  funder_info.csv   one row per funder: phone, website, how to apply, deadlines, restrictions, pre-selected only

    python -m funders contacts --out data/funders --top 250
"""
from __future__ import annotations

import csv
import json
import re
import struct
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

from funders import irs
from funders.match import norm_ein

KEEP_WHOLE = {"Filer", "BusinessOfficerGrp", "ApplicationSubmissionInfoGrp", "OfficerDirTrstKeyEmplGrp",
              "Form990PartVIISectionAGrp"}
STOP_AFTER = {"IRS990", "IRS990PF"}     # contact details sit in the main form; schedules after it are skipped
FEED = 256 * 1024
MAX_OFFICERS = 15
# a charity's own figures and words, kept when present (Form 990 Part I and Part III); funders ignore them
FACTS = {"CYTotalRevenueAmt", "CYContributionsGrantsAmt", "CYTotalExpensesAmt", "CYProgramServiceRevenueAmt",
         "ActivityOrMissionDesc", "MissionDesc", "TaxPeriodEndDt", "TotalEmployeeCnt", "TotalVolunteersCnt"}

# Part X groups for net assets a donor restricted (since 2018), and the older temporarily/permanently restricted ones
RESTRICTED = {"DonorRestrictionNetAssetsGrp", "TemporarilyRstrNetAssetsGrp", "PermanentlyRstrNetAssetsGrp"}

CONTACT_FIELDS = ["ein", "funder", "kind", "name", "title", "phone", "email", "address", "notes", "tax_year", "source"]
INFO_FIELDS = ["ein", "funder", "phone", "website", "preselected_only", "how_to_apply", "deadlines", "restrictions",
               "tax_year", "source"]


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _first(el, *names) -> str:
    for name in names:
        for d in el.iter():
            if _tag(d) == name and (d.text or "").strip():
                return " ".join(d.text.split())
    return ""


def _readable(name: str) -> str:
    """'JANE Q DOE' -> 'Jane Q Doe'; names already in mixed case are left alone."""
    if name and name.isupper():
        return " ".join(w if len(w) <= 3 and w in {"II", "III", "IV", "MD", "PHD", "JR", "SR", "LLC", "INC"} else w.capitalize()
                        for w in name.split())
    return name


def _phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    return f"({d[:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else (p or "")


def _address(el) -> str:
    parts = [_first(el, "AddressLine1Txt"), _first(el, "AddressLine2Txt")]
    city, st, z = _first(el, "CityNm"), _first(el, "StateAbbreviationCd"), _first(el, "ZIPCd")
    tail = " ".join(x for x in (f"{city}," if city else "", st, z) if x)
    return ", ".join(x for x in parts + [tail] if x)


def read_contacts(chunks) -> dict:
    """Parse one return as a stream and return its contact details."""
    out = {"phone": "", "website": "", "signer": None, "grants": [], "officers": [], "preselected_only": None,
           "tax_year": "", "return_type": "", "facts": {}}
    parser = ET.XMLPullParser(events=("start", "end"))
    stack, inside, done = [], 0, False

    def handle(el):
        nonlocal done
        t = _tag(el)
        if t == "Filer":
            out["phone"] = _phone(_first(el, "PhoneNum"))
        elif t == "TaxYr":
            out["tax_year"] = (el.text or "").strip()
        elif t == "ReturnTypeCd":
            out["return_type"] = (el.text or "").strip().upper().replace("-", "")
        elif t == "WebsiteAddressTxt" and not out["website"]:
            out["website"] = (el.text or "").strip()
        elif t == "OnlyContriToPreselectedInd":
            out["preselected_only"] = (el.text or "").strip().upper() in {"X", "1", "TRUE"}
        elif t == "BusinessOfficerGrp":
            out["signer"] = {"name": _readable(_first(el, "PersonNm")), "title": _first(el, "PersonTitleTxt"),
                             "phone": _phone(_first(el, "PhoneNum")), "email": _first(el, "EmailAddressTxt")}
        elif t == "ApplicationSubmissionInfoGrp":
            out["grants"].append({
                "name": _readable(_first(el, "RecipientPersonNm", "BusinessNameLine1Txt")),
                "phone": _phone(_first(el, "RecipientPhoneNum")), "email": _first(el, "RecipientEmailAddressTxt"),
                "address": _address(el), "materials": _first(el, "FormAndInfoAndMaterialsTxt"),
                "deadlines": _first(el, "SubmissionDeadlinesTxt"), "restrictions": _first(el, "RestrictionsOnAwardsTxt")})
        elif t == "OfficerDirTrstKeyEmplGrp":
            out["officers"].append({"name": _readable(_first(el, "PersonNm", "BusinessNameLine1Txt")),
                                    "title": _first(el, "TitleTxt"), "officer": True})
        elif t == "Form990PartVIISectionAGrp":
            flags = {_tag(d) for d in el.iter() if (d.text or "").strip().upper() in {"X", "1", "TRUE"}}
            out["officers"].append({"name": _readable(_first(el, "PersonNm", "BusinessNameLine1Txt")),
                                    "title": _first(el, "TitleTxt"),
                                    "officer": bool(flags & {"OfficerInd", "KeyEmployeeInd", "HighestCompensatedEmployeeInd"})})
        elif t == "EOYAmt" and stack and _tag(stack[-1]) in RESTRICTED and (el.text or "").strip():
            # net assets with donor restrictions at year end (Part X): gifts a donor tied to a purpose or a time
            try:
                out["facts"]["RestrictedNetAssetsEOY"] = out["facts"].get("RestrictedNetAssetsEOY", 0) + int(float(el.text))
            except ValueError:
                pass
        elif t in FACTS and t not in out["facts"] and (el.text or "").strip():
            out["facts"][t] = " ".join(el.text.split())
        elif t in STOP_AFTER:
            done = True

    def drop(el):
        if stack:
            try:
                stack[-1].remove(el)
            except ValueError:
                el.clear()

    for chunk in chunks:
        for i in range(0, len(chunk or b""), FEED):
            parser.feed(chunk[i:i + FEED])
            for event, el in parser.read_events():
                if event == "start":
                    stack.append(el)
                    inside += _tag(el) in KEEP_WHOLE
                    continue
                stack.pop()
                handle(el)
                inside -= _tag(el) in KEEP_WHOLE
                if inside == 0:
                    drop(el)
            if done:
                break
        if done:
            break
    if out["return_type"] == "990PF" and out["preselected_only"] is None:
        out["preselected_only"] = False
    # officers and key employees first, then directors; keep the list short enough to be useful
    out["officers"] = sorted(out["officers"], key=lambda o: not o["officer"])[:MAX_OFFICERS]
    return out


class _Archives:
    """Opens each archive's table of contents once and reads single returns from it by exact byte ranges."""

    def __init__(self, get=irs.http_range, size_of=irs.http_size, pause: float = irs.PAUSE):
        self.get, self.size_of, self.pause, self.dirs = get, size_of, pause, {}

    def _fetch(self, url, a, b):
        data = self.get(url, a, b)
        if self.pause:
            time.sleep(self.pause)
        return data

    def directory(self, url: str) -> dict:
        """An archive's table of contents (member file name -> where it sits), read once."""
        if url not in self.dirs:
            size = self.size_of(url)
            self.dirs[url] = {m.name.split("/")[-1]: m for m in irs.directory(size, lambda a, b: self._fetch(url, a, b))}
        return self.dirs[url]

    def chunks(self, source: str):
        url, _, name = source.partition("#")
        m = self.directory(url).get(name)
        if m is None:
            raise KeyError(f"{name} is not in {url.rsplit('/', 1)[-1]}")
        head = self._fetch(url, m.offset, m.offset + 29)
        nlen, xlen = struct.unpack("<HH", head[26:30])
        start = m.offset + 30 + nlen + xlen
        inflate = irs._decompressor(m.method)
        step = 4 * 1024 * 1024
        for pos in range(start, start + m.csize, step):
            yield from inflate(self._fetch(url, pos, min(start + m.csize, pos + step) - 1))


def latest_sources(out: Path) -> dict[str, str]:
    """Each funder's most recent return that paid a grant to a comparable organization."""
    best = {}
    path = out / "funders.jsonl"
    for ln in (path.read_text().splitlines() if path.exists() else []):
        if not ln.strip():
            continue
        r = json.loads(ln)
        e = norm_ein(r["funder_ein"])
        key = (r.get("tax_period_end") or "", r.get("source") or "")
        if e not in best or key > best[e][0]:
            best[e] = (key, r["source"])
    return {e: v[1] for e, v in best.items()}


def build(out_dir: str | Path, top: int = 250, get=irs.http_range, size_of=irs.http_size, pause: float = irs.PAUSE,
          log=print) -> dict:
    out = Path(out_dir)
    with (out / "funders.csv").open(newline="") as f:
        funders = [r for r in csv.DictReader(f) if r.get("persona") != "pass-through"][:top]
    sources = latest_sources(out)
    arcs = _Archives(get, size_of, pause)
    contacts, info, failed = [], [], []
    for i, f in enumerate(funders, 1):
        e = norm_ein(f["ein"])
        src = sources.get(e)
        if not src:
            failed.append(f["funder"])
            continue
        try:
            c = read_contacts(arcs.chunks(src))
        except (urllib.error.URLError, OSError, KeyError, ValueError, ET.ParseError) as ex:
            log(f"  can't read {f['funder']}: {ex}")
            failed.append(f["funder"])
            continue
        base = {"ein": f["ein"], "funder": f["funder"], "tax_year": c["tax_year"], "source": src}
        how = "; ".join(dict.fromkeys(g["materials"] for g in c["grants"] if g["materials"]))
        info.append({**base, "phone": c["phone"], "website": c["website"],
                     "preselected_only": "" if c["preselected_only"] is None else "yes" if c["preselected_only"] else "no",
                     "how_to_apply": how, "deadlines": "; ".join(dict.fromkeys(g["deadlines"] for g in c["grants"] if g["deadlines"])),
                     "restrictions": "; ".join(dict.fromkeys(g["restrictions"] for g in c["grants"] if g["restrictions"]))})
        for g in c["grants"]:
            if g["name"] or g["email"] or g["phone"]:
                contacts.append({**base, "kind": "grants contact", "name": g["name"] or "Grants contact", "title": "Grant requests",
                                 "phone": g["phone"], "email": g["email"], "address": g["address"],
                                 "notes": "Named in the foundation's 990-PF (Part XV) as the person to send grant requests to."})
        s = c["signer"]
        if s and s["name"]:
            contacts.append({**base, "kind": "signer", "name": s["name"], "title": s["title"], "phone": s["phone"], "email": s["email"],
                             "address": "", "notes": "Officer who signed the return."})
        for o in c["officers"]:
            if o["name"]:
                contacts.append({**base, "kind": "officer", "name": o["name"], "title": o["title"], "phone": "", "email": "",
                                 "address": "", "notes": "Listed on the return as an officer, director, trustee or key employee."})
        if i % 25 == 0:
            log(f"  {i} of {len(funders)} funders read")
    with (out / "contacts.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CONTACT_FIELDS)
        w.writeheader()
        w.writerows(contacts)
    with (out / "funder_info.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INFO_FIELDS)
        w.writeheader()
        w.writerows(info)
    res = {"funders": len(funders), "read": len(info), "contacts": len(contacts),
           "grants_contacts": sum(1 for c in contacts if c["kind"] == "grants contact"),
           "with_email": sum(1 for c in contacts if c["email"]), "with_phone": sum(1 for c in contacts if c["phone"]),
           "failed": failed}
    log(f"{res['read']} of {res['funders']} funders read: {res['contacts']} people ({res['grants_contacts']} grants contacts, "
        f"{res['with_phone']} with a phone, {res['with_email']} with an email)"
        + (f"; couldn't read {len(failed)}: {', '.join(failed[:5])}" if failed else ""))
    return res
