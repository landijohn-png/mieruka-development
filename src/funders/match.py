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


def load_seeds(path: str | Path) -> list[Seed]:
    data = tomllib.loads(Path(path).read_text())
    seeds = []
    for key, s in data.items():
        aliases = [norm_name(a) for a in [s["name"], *s.get("aliases", [])]]
        seeds.append(Seed(key=key, name=s["name"], persona=str(s.get("persona", "")),
                          aliases=list(dict.fromkeys(a for a in aliases if a)),
                          eins={norm_ein(e) for e in s.get("eins", []) if norm_ein(e)},
                          state=s.get("state", "").upper(),
                          purpose_words=[w.upper() for w in s.get("purpose_words", [])],
                          note=s.get("note", "")))
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
        if ein and ein in self.by_ein:
            return Match(self.by_ein[ein], "matched", "tax ID")
        n = norm_name(recipient)
        if not n:
            return None
        padded = f" {n} "
        best = None
        for s in self.seeds:
            for a in s.aliases:
                if n == a:
                    if ein and s.eins:
                        return Match(s, "review", f"name matches but tax ID {ein} is not {s.name}'s")
                    if s.purpose_words and not any(w in purpose.upper() for w in s.purpose_words):
                        return Match(s, "review", "name matches; purpose doesn't mention "
                                     + " / ".join(s.purpose_words[:3]).lower())
                    if s.state and recipient_state and recipient_state.upper() != s.state:
                        return Match(s, "review", f"name matches; recipient is in {recipient_state}, "
                                     f"{s.name} is in {s.state}")
                    return Match(s, "matched", "name")
                if len(a) >= 8 and f" {a} " in padded and best is None:
                    best = Match(s, "review", f"name contains \"{a.title()}\"")
        return best
