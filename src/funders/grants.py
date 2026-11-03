"""Read the grants a return reports paying: Form 990-PF Part XV and Schedule I of Form 990.

Returns are parsed as a stream so a donor-advised fund's Schedule I with hundreds of thousands
of grants never has to sit in memory as one tree.
"""
from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable

PF_GRANT = "GrantOrContributionPdDurYrGrp"     # Form 990-PF, Part XV line 3a
SCHED_I_GRANT = "RecipientTable"               # Schedule I (Form 990), Part II
GRANT_TAGS = (PF_GRANT.encode(), SCHED_I_GRANT.encode())


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _find_text(el, *names) -> str:
    """Text of the first descendant whose local tag is one of names (in order of preference)."""
    for name in names:
        for d in el.iter():
            if _tag(d) == name and (d.text or "").strip():
                return d.text.strip()
    return ""


def _num(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Grant:
    recipient: str
    recipient_ein: str
    recipient_state: str
    amount: float
    purpose: str


@dataclass
class ReturnGrants:
    funder_ein: str = ""
    funder_name: str = ""
    funder_state: str = ""
    return_type: str = ""
    tax_year: str = ""
    tax_period_end: str = ""
    preselected_only: bool | None = None    # 990-PF Part XV line 2; None for Form 990 filers
    grants: list[Grant] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)   # every grant in the return
    recipient_states: set[str] = field(default_factory=set)

    @property
    def total_paid(self) -> float:
        return sum(self.amounts)

    @property
    def median_grant(self) -> float | None:
        return statistics.median(self.amounts) if self.amounts else None


def has_grants(head: bytes) -> bool:
    return any(t in head for t in GRANT_TAGS)


def read(chunks: Iterable[bytes], keep=lambda g: True) -> ReturnGrants:
    """Parse one return. Every grant counts toward the funder's totals; only grants for which
    keep(grant) is true are kept in .grants."""
    out = ReturnGrants()
    parser = ET.XMLPullParser(events=("start", "end"))
    in_header = True
    stack = []

    def drop(el):
        """Forget a finished element entirely, so huge grant tables don't pile up in memory."""
        if len(stack) >= 1:
            try:
                stack[-1].remove(el)
            except ValueError:
                el.clear()

    def handle(el):
        nonlocal in_header
        t = _tag(el)
        if in_header:
            if t == "Filer":
                out.funder_ein = _find_text(el, "EIN")
                out.funder_name = _find_text(el, "BusinessNameLine1Txt", "BusinessNameLine1")
                out.funder_state = _find_text(el, "StateAbbreviationCd", "State")
            elif t == "ReturnTypeCd":
                out.return_type = (el.text or "").strip().upper().replace("-", "")
            elif t == "TaxYr":
                out.tax_year = (el.text or "").strip()
            elif t == "TaxPeriodEndDt":
                out.tax_period_end = (el.text or "").strip()
            elif t == "ReturnHeader":
                in_header = False
                drop(el)
            return
        if t == PF_GRANT:
            g = Grant(recipient=_find_text(el, "BusinessNameLine1Txt", "RecipientPersonNm"),
                      recipient_ein=_find_text(el, "RecipientEIN"),
                      recipient_state=_find_text(el, "StateAbbreviationCd"),
                      amount=_num(_find_text(el, "Amt")),
                      purpose=_find_text(el, "GrantOrContributionPurposeTxt"))
            _add(g)
            drop(el)
        elif t == SCHED_I_GRANT:
            g = Grant(recipient=_find_text(el, "BusinessNameLine1Txt"),
                      recipient_ein=_find_text(el, "RecipientEIN"),
                      recipient_state=_find_text(el, "StateAbbreviationCd"),
                      amount=_num(_find_text(el, "CashGrantAmt")) + _num(_find_text(el, "NonCashAssistanceAmt")),
                      purpose=_find_text(el, "PurposeOfGrantTxt"))
            _add(g)
            drop(el)
        elif t == "OnlyContriToPreselectedInd":
            out.preselected_only = (el.text or "").strip().upper() in {"X", "1", "TRUE"}
        elif t in ("SupplementaryInformationGrp", "IRS990ScheduleI", "IRS990", "IRS990PF"):
            drop(el)

    def _add(g: Grant):
        if g.amount:
            out.amounts.append(g.amount)
        if g.recipient_state:
            out.recipient_states.add(g.recipient_state)
        if keep(g):
            out.grants.append(g)

    def drain():
        for event, el in parser.read_events():
            if event == "start":
                stack.append(el)
            else:
                stack.pop()
                handle(el)

    for chunk in chunks:
        if chunk:
            parser.feed(chunk)
            drain()
    parser.close()
    drain()
    if out.return_type == "990PF" and out.preselected_only is None:
        out.preselected_only = False
    return out
