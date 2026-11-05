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

# who to contact at the top 250: reads only each funder's latest filing (a few minutes)
python -m funders contacts --out data/funders --top 250
```

The scan reads each IRS archive front to back in 16 MB windows (nothing is saved but the grants
it finds) and remembers which archives are done, so it can be stopped and started again.

## What comes out (in the --out folder)

| File | What it holds |
|---|---|
| `funders.csv` | Every funder of a comparable organization, highest priority first, with links to the filings |
| `sweep_import.csv` | The top 100, as leads for the Sweep Console |
| `review.csv` | Uncertain matches. Write `yes` or `no` in `decision`, then run `report` again |
| `contacts.csv` | People at each funder: the grants contact a foundation names (phone, email, mailing address), the officer who signed, and officers, directors and trustees with titles. Officers' home addresses are never kept |
| `funder_info.csv` | Each funder's phone, website, what to submit, deadlines, restrictions, and whether it funds only pre-selected organizations |
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

## Charities and advisors (on John's PC)

Two more lists, built the same way from public filings, for the Mieruka console's Charities and Advisors
sections. Light enough for the PC; the test server stays Mieruka-only.

```
Build Lists.bat                     (in C:\Mieruka\mieruka-development: sets up Python the first time, then builds both lists)

python -m funders charities --out C:\Mieruka\Data\charities --targets C:\Mieruka\Data\outreach_targets_charities.csv
python -m funders advisors --sec-file C:\Mieruka\Data\advisors --out C:\Mieruka\Data\advisors --targets C:\Mieruka\Data\outreach_targets_advisors.csv
```

**Charities** come from the IRS list of exempt organizations in Pennsylvania (eo_pa.csv) and the Census ZIP-to-county
file: public charities in Westmoreland, Allegheny and the seven counties around them with revenue $500K to $50M
(private foundations and grantmakers are funders, not pilot charities). The first 400 have their latest Form 990 read
for phone, website, mission, revenue, contributions and the people it lists.

**Advisors** come from the SEC's monthly list of registered investment advisers. The SEC asks automated downloads to
give a contact address, so download it by hand: on sec.gov, "Information About Registered Investment Advisers and
Exempt Reporting Advisers", the newest **Registered Investment Advisers** ZIP, saved into `C:\Mieruka\Data\advisors`.
Firms registered only with Pennsylvania (most small ones) aren't in it; the targets list and your network cover those.

**Call order** (A call first, then B, then C) is John's outreach plan, from stated facts only, never a judgment of a
charity's work, and never shown to a charity or in the product. Rows from the outreach targets list keep the order
and notes given there.

| List | A | B |
|---|---|---|
| Charities | Westmoreland or Allegheny, revenue $1M–$25M, 35%+ of revenue from contributions | In the counties, 15%+ from contributions |
| Advisors | Westmoreland or Allegheny, 25+ high-net-worth clients, $100M–$5B under management | In the counties, 10+ high-net-worth clients |

| File | What it holds |
|---|---|
| `charities.csv` | Each charity in call order, why (the facts), cause, revenue, contributions, net assets with donor restrictions (the gifts Mieruka reports on), phone, website, mission, filing link |
| `charity_contacts.csv` | People named on its latest 990: the officer who signed, executive and development leads first |
| `advisors.csv` | Each firm in call order, why, SEC number, assets, clients by type, phone, website, public record link |
| `advisor_contacts.csv` | The compliance officer the firm's Form ADV names, when the SEC file includes it |

Families are never listed or looked up: they come to Mieruka through their advisor.
