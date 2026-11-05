"""Working rules for this repository (see CLAUDE.md), enforced."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = (".csv", ".jsonl", ".json", ".xlsx", ".db", ".sqlite", ".zip", ".parquet")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


def test_no_data_files_tracked():
    bad = [p for p in tracked() if p.lower().endswith(DATA)]
    assert not bad, f"Scan results and other data stay out of git: {bad}"


def test_nothing_from_the_donor_product_is_imported():
    # Family and gift data live only in the Mieruka product; these tools never touch them.
    for p in (ROOT / "src").rglob("*.py"):
        text = p.read_text()
        assert "import mieruka" not in text and "from mieruka" not in text, p.name


def test_families_are_never_listed_or_looked_up():
    # Families come to Mieruka through their advisor; no tool here builds a list of them.
    names = [p.stem.lower() for p in (ROOT / "src").rglob("*.py")]
    assert not any("famil" in n or "donor" in n for n in names), names
