"""Where an organization is: ZIP code to county, from the Census Bureau's public ZIP-to-county file, and a small
download cache so a second run doesn't fetch the same public files again.

Counties are Western Pennsylvania's by default, with Westmoreland and Allegheny as home (Mieruka is in Ligonier).
"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from funders import irs

ZCTA_COUNTY = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"

COUNTIES = {"Westmoreland": "42129", "Allegheny": "42003", "Washington": "42125", "Butler": "42019", "Beaver": "42007",
            "Fayette": "42051", "Somerset": "42111", "Indiana": "42063", "Armstrong": "42005"}
HOME = ("Westmoreland", "Allegheny")
CACHE_DAYS = 30


def cached(url: str, folder: Path, get=irs.http_range, days: int = CACHE_DAYS, log=print) -> bytes:
    """A public file, downloaded once and kept in folder/cache for a month."""
    cache = Path(folder) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / url.rsplit("/", 1)[-1]
    if path.exists() and time.time() - path.stat().st_mtime < days * 86400:
        return path.read_bytes()
    log(f"  downloading {url}")
    data = get(url, None, None)
    path.write_bytes(data)
    return data


def zip_to_county(data: bytes | str, fips: set[str]) -> dict[str, str]:
    """ZIP code -> county FIPS, for ZIPs in the wanted counties. A ZIP spread over several counties goes to the one
    holding most of its land."""
    text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else data
    rows = csv.reader(io.StringIO(text), delimiter="|")
    head = [h.strip().upper() for h in next(rows, [])]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        raise ValueError(f"ZIP-to-county file is missing {names[0]}")
    i_zip, i_cty = col("GEOID_ZCTA5_20", "ZCTA5"), col("GEOID_COUNTY_20", "COUNTY")
    i_land = col("AREALAND_PART", "AREALAND")
    best: dict[str, tuple[int, str]] = {}
    for r in rows:
        if len(r) <= max(i_zip, i_cty, i_land) or not r[i_zip].strip():
            continue
        z, c = r[i_zip].strip().zfill(5), r[i_cty].strip()
        try:
            land = int(r[i_land] or 0)
        except ValueError:
            land = 0
        if z not in best or land > best[z][0]:
            best[z] = (land, c)
    return {z: c for z, (land, c) in best.items() if c in fips}


def county_names(fips_by_name: dict[str, str] = COUNTIES) -> dict[str, str]:
    return {v: k for k, v in fips_by_name.items()}
