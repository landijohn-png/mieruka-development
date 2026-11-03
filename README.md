# Mieruka development tools

Fundraising tools for Project Mieruka itself. First tool: the **funder finder**, which reads IRS
e-file filings to find every foundation, donor-advised fund and charity that has paid grants to
organizations like Mieruka (Charity Navigator, Candid, ProPublica, Fast Forward and others in
`config/seeds.toml`), then ranks them as prospects using the Funder Persona Playbook.

## Set up (on the test server, next to Mieruka)

```
git clone git@github.com:landijohn-png/mieruka-development.git ~/mieruka-development
cd ~/mieruka-development
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]" && pytest
```

## Run

```
# trial: one archive, a few minutes
python -m funders scan --years 2025 --max-zips 1 --out data/trial
python -m funders report --out data/trial

# full run: IRS publication years 2023 to 2025, every Form 990 and 990-PF nationwide
nohup python -m funders scan --years 2025 2024 2023 --out data/funders > data/scan.log 2>&1 &
python -m funders report --out data/funders
```

The scan reads each IRS archive front to back in 16 MB windows (nothing is saved but the grants
it finds) and remembers which archives are done, so it can be stopped and started again.

## What comes out (in the --out folder)

| File | What it holds |
|---|---|
| `funders.csv` | Every funder of a comparable organization, highest priority first, with links to the filings |
| `sweep_import.csv` | The top 100, as leads for the Sweep Console |
| `review.csv` | Uncertain matches. Write `yes` or `no` in `decision`, then run `report` again |
| `recipient_eins.txt` | Tax IDs recipients filed under each comparable's name, to confirm in `config/seeds.toml` |

## How a grant counts

| Situation | Result |
|---|---|
| Recipient's tax ID is a comparable's confirmed tax ID | Counts |
| Exact name, nothing contradicting it | Counts |
| Exact name but another state, another tax ID, or (for large institutes) an unrelated purpose | Review |
| Name contains a comparable's name | Review |

## Priority (0 to 100)

| Factor | Points | Full points when |
|---|---|---|
| Breadth | 30 | Funded 4 or more comparables |
| Recency | 20 | Latest such grant in tax year 2024 or later (2023: 14, 2022: 8) |
| Size fit | 20 | Median grant $10K to $250K ($5K to $1M: 10) |
| Geography | 15 | Pennsylvania, or grants to 5+ states |
| Openness | 15 | Foundation accepts unsolicited requests (public charities and DAFs: 8, unknown) |

Personas are tagged by simple rules (DAF or wealth-management name → 4, corporate name → 3,
Pennsylvania → 1, foundation paying $25M+ a year → 2); the rest are left for a person.
Set any funder's persona by tax ID in `config/personas.toml`.

## Limits

- Schedule I lists only grants over $5,000, so small gifts from public charities and DAFs are missed.
- IRS e-file data runs 12 to 18 months behind; the newest grants aren't there yet.
- Some foundations attach grant lists as PDFs instead of filing them line by line; those are missed.
