# Mieruka development tools: working rules

This repository holds Project Mieruka's own fundraising tools, kept apart from the donor product
(landijohn-png/mieruka-mieruka), whose rules forbid ranking charities. Here we rank *funder
prospects for Mieruka itself*; that ranking never appears in the product or describes a charity to donors.

1. **Public filings only.** Use only public IRS filings and public funder information. No donor, family, advisor or gift data, ever; nothing here imports the Mieruka product.
2. **Keep the source.** Every grant found keeps the link to the filing it came from.
3. **A person decides.** Uncertain matches go to review.csv; outreach and personas are a person's call.
4. **No data in git.** Scan results live in `data/` (ignored) or on the server.
5. **Be gentle with the IRS server.** Large windowed reads with a pause between requests.

Run `pytest` before every commit. Python 3.11 or newer.
