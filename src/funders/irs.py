"""Read IRS Form 990 e-file archives as a stream, a window at a time, without saving them.

The IRS publishes each year's returns as large ZIP archives and an index (CSV). The funder finder
needs nearly every Form 990 and 990-PF in an archive, so instead of one request per return (as
Mieruka's efile.py does for a few charities) this reads the archive front to back in large
windows and decompresses each wanted return in turn. Nothing is written to disk.

The HTTP helpers and ZIP directory reading are adapted from Project Mieruka's src/mieruka/efile.py.
"""
from __future__ import annotations

import csv
import http.client
import io
import re
import struct
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Callable, Iterator

BASE = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/"
INDEX = BASE + "index_{year}.csv"
ZIP = BASE + "{batch}.zip"
DOWNLOADS_PAGE = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
UA = {"User-Agent": "Project Mieruka funder research (nonprofit)"}

WINDOW = 16 * 1024 * 1024      # bytes fetched per request when reading an archive front to back
PAUSE = 0.2                    # seconds between requests, to be gentle with the IRS server
RETRIES = 3

Fetch = Callable[[str, int | None, int | None], bytes]


def _retry(fn):
    for attempt in range(RETRIES):
        try:
            return fn()
        except urllib.error.HTTPError:
            raise
        except (OSError, http.client.HTTPException):
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))


def http_range(url: str, start: int | None = None, end: int | None = None) -> bytes:
    headers = dict(UA)
    if start is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"

    def go():
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as r:
            return r.read()
    return _retry(go)


def http_size(url: str) -> int:
    def go():
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"), timeout=60) as r:
            return int(r.headers["Content-Length"])
    return _retry(go)


def published_zips(year: int, get: Fetch = http_range) -> list[str]:
    """Archive names the IRS downloads page lists for a year."""
    html = get(DOWNLOADS_PAGE, None, None).decode("utf-8", "replace")
    names = re.findall(rf"/xml/{year}/([A-Za-z0-9_]+)\.zip", html)
    return list(dict.fromkeys(names))


@dataclass(frozen=True)
class IndexRow:
    object_id: str
    ein: str
    return_type: str
    tax_period: str
    name: str
    batch: str


def read_index(text: str, return_types=("990", "990PF")) -> dict[str, IndexRow]:
    """Index rows for the wanted return types, keyed by object id."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip().upper(): (v or "").strip() for k, v in row.items() if k}
        rt = row.get("RETURN_TYPE", "").upper().replace("-", "")
        if rt in return_types and row.get("OBJECT_ID"):
            out[row["OBJECT_ID"]] = IndexRow(row["OBJECT_ID"], re.sub(r"\D", "", row.get("EIN", "")), rt,
                                             row.get("TAX_PERIOD", ""), row.get("TAXPAYER_NAME", ""),
                                             row.get("XML_BATCH_ID", "").upper())
    return out


@dataclass(frozen=True)
class Member:
    name: str
    offset: int
    csize: int
    usize: int
    method: int

    @property
    def object_id(self) -> str:
        return self.name.split("/")[-1].split("_")[0]


def directory(size: int, fetch: Callable[[int, int], bytes]) -> list[Member]:
    """The members of a ZIP archive, read from its central directory (ZIP64 aware)."""
    tail = fetch(max(0, size - 65_557), size - 1)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0:
        raise ValueError("Not a ZIP archive (no end-of-directory record).")
    n, cd_size, cd_off = struct.unpack("<HII", tail[pos + 10:pos + 20])
    if cd_off == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        loc = tail.rfind(b"PK\x06\x07")
        (eocd64_off,) = struct.unpack("<Q", tail[loc + 8:loc + 16])
        rec = fetch(eocd64_off, eocd64_off + 55)
        n, cd_size, cd_off = struct.unpack("<QQQ", rec[32:56])
    cd = fetch(cd_off, cd_off + cd_size - 1)
    out, i = [], 0
    while i + 46 <= len(cd) and cd[i:i + 4] == b"PK\x01\x02":
        (method,) = struct.unpack("<H", cd[i + 10:i + 12])
        csize, usize = struct.unpack("<II", cd[i + 20:i + 28])
        nlen, xlen, clen = struct.unpack("<HHH", cd[i + 28:i + 34])
        (off,) = struct.unpack("<I", cd[i + 42:i + 46])
        name = cd[i + 46:i + 46 + nlen].decode("utf-8", "replace")
        extra = cd[i + 46 + nlen:i + 46 + nlen + xlen]
        j = 0
        while j + 4 <= len(extra):
            hid, hlen = struct.unpack("<HH", extra[j:j + 4])
            if hid == 1:
                vals = list(struct.unpack("<" + "Q" * (hlen // 8), extra[j + 4:j + 4 + (hlen // 8) * 8]))
                if usize == 0xFFFFFFFF and vals: usize = vals.pop(0)
                if csize == 0xFFFFFFFF and vals: csize = vals.pop(0)
                if off == 0xFFFFFFFF and vals: off = vals.pop(0)
            j += 4 + hlen
        if not name.endswith("/"):
            out.append(Member(name, off, csize, usize, method))
        i += 46 + nlen + xlen + clen
    return out


def _decompressor(method: int):
    if method == 0:
        return lambda b: b
    if method == 8:
        d = zlib.decompressobj(-15)
        return d.decompress
    if method == 9:   # Deflate64, used in some IRS archives (2025 and later)
        import inflate64
        return inflate64.Inflater().inflate
    raise ValueError(f"Unsupported compression method {method}.")


class Archive:
    """One IRS archive, read front to back in large windows."""

    def __init__(self, url: str, get: Fetch = http_range, size_of=http_size, window: int = WINDOW,
                 pause: float = PAUSE):
        self.url, self.get, self.window, self.pause = url, get, window, pause
        self.size = size_of(url)
        self.members = directory(self.size, lambda a, b: self._get(a, b))
        self._buf_start, self._buf = 0, b""

    def _get(self, a: int, b: int) -> bytes:
        data = self.get(self.url, a, b)
        if self.pause:
            time.sleep(self.pause)
        return data

    def _span(self, a: int, b: int) -> bytes:
        """Bytes a..b inclusive, from the current window or a new one starting at a."""
        end = self._buf_start + len(self._buf)
        if not (self._buf_start <= a and b < end):
            stop = min(self.size - 1, max(b, a + self.window - 1))
            self._buf_start, self._buf = a, self._get(a, stop)
        return self._buf[a - self._buf_start:b - self._buf_start + 1]

    def stream(self, wanted: set[str] | None = None) -> Iterator[tuple[Member, Iterator[bytes]]]:
        """Yield (member, chunks) for each wanted object id, in archive order. Each member's
        chunks must be consumed (or abandoned) before asking for the next member."""
        members = sorted((m for m in self.members if wanted is None or m.object_id in wanted),
                         key=lambda m: m.offset)
        for m in members:
            head = self._span(m.offset, m.offset + 29)
            if head[:4] != b"PK\x03\x04":
                raise ValueError(f"Bad local header for {m.name}")
            nlen, xlen = struct.unpack("<HH", head[26:30])
            start = m.offset + 30 + nlen + xlen
            yield m, self._chunks(m, start)

    def _chunks(self, m: Member, start: int) -> Iterator[bytes]:
        inflate = _decompressor(m.method)
        if m.csize == 0:
            return
        if m.csize <= self.window:
            yield inflate(self._span(start, start + m.csize - 1))
            return
        pos, stop = start, start + m.csize
        while pos < stop:
            end = min(stop, pos + self.window) - 1
            yield inflate(self._span(pos, end))
            pos = end + 1
