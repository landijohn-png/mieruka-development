import os
import zipfile
import io

from funders import irs
from helpers import FakeIRS, make_zip


def test_stream_reads_wanted_members_in_small_windows():
    bodies = {f"20250{i}_public.xml": (f"<x>{i}</x>" + "y" * (i * 300)).encode() + os.urandom(50).hex().encode()
              for i in range(1, 6)}
    fake = FakeIRS(2025, {"2025_TEOS_XML_01A": make_zip(bodies)}, [])
    url = irs.ZIP.format(year=2025, batch="2025_TEOS_XML_01A")
    arc = irs.Archive(url, get=fake.get, size_of=fake.size, window=256, pause=0)
    got = {m.object_id: b"".join(ch) for m, ch in arc.stream({"202502", "202504", "202505"})}
    assert set(got) == {"202502", "202504", "202505"}
    for oid, body in got.items():
        assert body == bodies[f"{oid}_public.xml"]


def test_stream_uses_few_requests_with_a_large_window():
    bodies = {f"20250{i}_public.xml": b"<x>" + b"z" * 2000 + b"</x>" for i in range(1, 9)}
    fake = FakeIRS(2025, {"B": make_zip(bodies)}, [])
    arc = irs.Archive(irs.ZIP.format(year=2025, batch="B"), get=fake.get, size_of=fake.size, window=1 << 20, pause=0)
    before = fake.requests
    assert len([b"".join(c) for _, c in arc.stream()]) == 8
    assert fake.requests - before == 1


def test_read_index_keeps_990_and_990pf_only():
    text = ("RETURN_ID,EIN,TAX_PERIOD,TAXPAYER_NAME,RETURN_TYPE,OBJECT_ID,XML_BATCH_ID\n"
            "1,12-3456789,202412,A,990PF,111,01a\n2,123456780,202412,B,990EZ,222,01a\n3,1,202412,C,990,333,\n")
    idx = irs.read_index(text)
    assert set(idx) == {"111", "333"}
    assert idx["111"].ein == "123456789" and idx["111"].batch == "01A"
