"""Scan IRS e-file archives for grants paid to the comparable organizations.

Writes, under the output folder:
  grants.jsonl    one line per grant to a comparable organization (matched or for review)
  funders.jsonl   one line per return that paid such a grant: the funder and its overall giving
  progress.json   archives already scanned, so a stopped run picks up where it left off
  scan_<date>.txt a plain log of the run
"""
from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path

from funders import grants as G
from funders import irs
from funders.match import Matcher

BIG = 8 * 1024 * 1024     # returns larger than this (uncompressed) are parsed as a stream, no quick test
EVERY = 5000              # log progress inside an archive every this many returns


def scan_year(year: int, matcher: Matcher, out: Path, get=irs.http_range, size_of=irs.http_size,
              log=print, max_zips: int | None = None, window: int = irs.WINDOW, pause: float = irs.PAUSE) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    progress_path = out / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {"done": []}
    done = set(progress["done"])

    index = irs.read_index(get(irs.INDEX.format(year=year), None, None))
    log(f"{year}: {len(index):,} Form 990 and 990-PF returns in the index (memory {irs.rss_mb()} MB)")
    try:
        batches = irs.published_zips(year, get)
    except urllib.error.HTTPError:
        batches = []
    if not batches:   # fall back to the batch names the index gives
        batches = sorted(index.batches)
    stats = {"archives": 0, "returns": 0, "parsed": 0, "matched": 0, "review": 0, "failed": 0}

    for batch in batches:
        if max_zips is not None and stats["archives"] >= max_zips:
            break
        url = irs.ZIP.format(year=year, batch=batch)
        if url in done:
            continue
        try:
            arc = irs.Archive(url, get=get, size_of=size_of, window=window, pause=pause)
        except (urllib.error.HTTPError, ValueError) as ex:
            log(f"  can't open {batch}: {ex}")
            continue
        wanted = {m.object_id for m in arc.members if m.object_id in index}
        log(f"  {batch}: {len(wanted):,} returns to read (memory {irs.rss_mb()} MB)")
        found = []
        funders = {}
        n_in_archive = 0
        for m, chunks in arc.stream(wanted):
            stats["returns"] += 1
            n_in_archive += 1
            if n_in_archive % EVERY == 0:
                log(f"    {n_in_archive:,} of {len(wanted):,} read, {len(found)} grants so far (memory {irs.rss_mb()} MB)")
            if m.usize > BIG:
                log(f"    large return {m.object_id} ({m.usize / 1e6:,.0f} MB), reading it as a stream")
            source = f"{url}#{m.name.split('/')[-1]}"
            try:
                if m.usize <= BIG:
                    raw = b"".join(chunks)
                    if not G.has_grants(raw) or not matcher.might_match(raw.upper()):
                        continue
                    chunks = iter([raw])
                stats["parsed"] += 1
                hits = []

                def keep(g):
                    hit = matcher.match(g.recipient, g.recipient_ein, g.recipient_state, g.purpose)
                    if hit:
                        hits.append((g, hit))
                    return False
                rg = G.read(chunks, keep=keep)
            except MemoryError:
                stats["failed"] += 1
                chunks = raw = None
                log(f"    skipped {m.object_id}: too large for the memory ceiling ({m.usize / 1e6:,.0f} MB unpacked)")
                with (out / "skipped.txt").open("a") as f:
                    f.write(f"{source}\ttoo large for memory\n")
                continue
            except Exception as ex:   # one unreadable return never stops the run
                stats["failed"] += 1
                log(f"    can't read {m.name}: {ex}")
                with (out / "skipped.txt").open("a") as f:
                    f.write(f"{source}\t{ex}\n")
                continue
            if not hits:
                continue
            ein = rg.funder_ein
            for g, hit in hits:
                stats[hit.status] += 1
                found.append({
                    "status": hit.status, "reason": hit.reason, "seed": hit.seed.key, "seed_name": hit.seed.name,
                    "funder_ein": ein, "funder_name": rg.funder_name,
                    "tax_year": rg.tax_year, "tax_period_end": rg.tax_period_end, "return_type": rg.return_type,
                    "recipient": g.recipient, "recipient_ein": g.recipient_ein, "recipient_state": g.recipient_state,
                    "amount": g.amount, "purpose": g.purpose, "object_id": m.object_id, "source": source,
                })
            funders[m.object_id] = {
                "funder_ein": ein, "funder_name": rg.funder_name, "funder_state": rg.funder_state,
                "return_type": rg.return_type, "tax_year": rg.tax_year,
                "tax_period_end": rg.tax_period_end, "preselected_only": rg.preselected_only,
                "total_paid": rg.total_paid, "grant_count": len(rg.amounts), "median_grant": rg.median_grant,
                "recipient_states": len(rg.recipient_states), "object_id": m.object_id, "source": source,
            }
        with (out / "grants.jsonl").open("a") as f:
            for r in found:
                f.write(json.dumps(r) + "\n")
        with (out / "funders.jsonl").open("a") as f:
            for r in funders.values():
                f.write(json.dumps(r) + "\n")
        done.add(url)
        progress["done"] = sorted(done)
        progress_path.write_text(json.dumps(progress, indent=1))
        stats["archives"] += 1
        log(f"    {len(found)} grants to comparable organizations ({sum(1 for r in found if r['status'] == 'review')} to review)")
    log(f"{year}: {stats['archives']} archives, {stats['returns']:,} returns read, {stats['parsed']:,} parsed, "
        f"{stats['matched']} grants matched, {stats['review']} to review, {stats['failed']} unreadable")
    return stats


def scan(years, matcher: Matcher, out: str | Path, **kw) -> list[dict]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    logfile = (out / f"scan_{time.strftime('%Y-%m-%d')}.txt").open("a")

    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        logfile.write(line + "\n")
        logfile.flush()
    try:
        return [scan_year(y, matcher, out, log=log, **kw) for y in years]
    finally:
        logfile.close()
