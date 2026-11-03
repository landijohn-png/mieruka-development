"""Decide whether a grant recipient is one of the comparable organizations ("seeds").

A tax ID match, or an exact name match with nothing contradicting it, counts as matched.
Anything less certain goes to the review list for a person to decide. Nothing is guessed.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SUFFIXES = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "LLC", "LTD", "THE"}


def norm_name(name: str) -> str:
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    words = [w for w in s.split() if w]
    while words and words[0] == "THE":
        words.pop(0)
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def norm_ein(ein: str) -> str:
    d = re.sub(r"\D", "", ein or "")
    return d.zfill(9) if d else ""


@dataclass
class Seed:
    key: str
    name: str
    persona: str
    aliases: list[str]
    eins: set[str] = field(default_factory=set)
    state: str = ""
    purpose_words: list[str] = field(default_factory=list)
    note: str = ""
    unique: bool = False               # exact name counts wherever the recipient's address is
    contains_ok: bool = False          # a longer name containing an alias counts (e.g. "ProPublica Illinois")
    exact_only: set[str] = field(default_factory=set)    # aliases too generic to match inside longer names
    exclude_words: list[str] = field(default_factory=list)
    exclude_eins: set[str] = field(default_factory=set)
    purpose_strict: bool = False       # a grant whose purpose doesn't fit doesn't count at all (no review)


def load_seeds(path: str | Path) -> list[Seed]:
    data = tomllib.loads(Path(path).read_text())
    seeds = []
    for key, s in data.items():
        raw = [s["name"], *s.get("aliases", [])]
        aliases = [norm_name(a.lstrip("=")) for a in raw]
        seeds.append(Seed(key=key, name=s["name"], persona=str(s.get("persona", "")),
                          aliases=list(dict.fromkeys(a for a in aliases if a)),
                          eins={norm_ein(e) for e in s.get("eins", []) if norm_ein(e)},
                          state=s.get("state", "").upper(),
                          purpose_words=[w.upper() for w in s.get("purpose_words", [])],
                          note=s.get("note", ""),
                          unique=bool(s.get("unique", False)),
                          contains_ok=bool(s.get("contains_ok", False)),
                          exact_only={norm_name(a[1:]) for a in raw if a.startswith("=")},
                          exclude_words=[norm_name(w) for w in s.get("exclude_words", []) if norm_name(w)],
                          exclude_eins={norm_ein(e) for e in s.get("exclude_eins", []) if norm_ein(e)},
                          purpose_strict=bool(s.get("purpose_strict", False))))
    return seeds


COMMON = {"FOUNDATION", "CENTER", "NETWORK", "INSTITUTE", "FUND", "FUNDS", "NATIONAL", "AMERICA",
          "AMERICAN", "GLOBAL", "PHILANTHROPY", "NONPROFIT", "TECHNOLOGY", "GREATER", "WESTERN", "OF", "AND"}


def _needle(alias: str) -> str:
    words = [w for w in alias.split() if w not in COMMON]
    return max(words, key=len) if words else alias


@dataclass(frozen=True)
class Match:
    seed: Seed
    status: str          # "matched" or "review"
    reason: str


class Matcher:
    def __init__(self, seeds: list[Seed]):
        self.seeds = seeds
        self.by_ein = {e: s for s in seeds for e in s.eins}
        # quick byte test so most returns are never parsed: any alias or tax ID present at all
        # (the longest word of each alias, so punctuation or "&" in the filed name can't hide it)
        needles = {_needle(a) for s in seeds for a in s.aliases}
        self.needles = sorted({n.encode() for n in needles} | {e.encode() for e in self.by_ein})

    def might_match(self, raw_upper: bytes) -> bool:
        return any(n in raw_upper for n in self.needles)

    def match(self, recipient: str, recipient_ein: str = "", recipient_state: str = "",
              purpose: str = "") -> Match | None:
        ein = norm_ein(recipient_ein)
        n = norm_name(recipient)
        padded = f" {n} "

        def purpose_ok(s: Seed) -> bool:
            return not s.purpose_words or any(w in purpose.upper() for w in s.purpose_words)

        def excluded(s: Seed) -> bool:
            return (ein and ein in s.exclude_eins) or any(f" {w} " in padded for w in s.exclude_words)

        if ein and ein in self.by_ein:
            s = self.by_ein[ein]
            if not purpose_ok(s) and s.purpose_strict:
                return None
            if not purpose_ok(s):
                return Match(s, "review", "purpose doesn't mention " + " / ".join(s.purpose_words[:3]).lower())
            return Match(s, "matched", "tax ID")
        if not n:
            return None
        best = None
        for s in self.seeds:
            if excluded(s) or (s.purpose_strict and not purpose_ok(s)):
                continue
            for a in s.aliases:
                if n == a:
                    if ein and s.eins:
                        return Match(s, "review", f"name matches but tax ID {ein} is not {s.name}'s")
                    if not purpose_ok(s):
                        return Match(s, "review", "name matches; purpose doesn't mention "
                                     + " / ".join(s.purpose_words[:3]).lower())
                    if s.state and recipient_state and recipient_state.upper() != s.state and not s.unique:
                        return Match(s, "review", f"name matches; recipient is in {recipient_state}, "
                                     f"{s.name} is in {s.state}")
                    return Match(s, "matched", "name")
                if best is None and a not in s.exact_only and len(a) >= 8 and f" {a} " in padded:
                    if s.contains_ok and not (ein and s.eins) and purpose_ok(s):
                        best = Match(s, "matched", f"name contains \"{a.title()}\"")
                    else:
                        best = Match(s, "review", f"name contains \"{a.title()}\"")
        return best
