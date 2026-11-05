# Mieruka development tools: working rules

This repository holds Project Mieruka's own outreach tools, kept apart from the donor product
(landijohn-png/mieruka-mieruka), whose rules forbid ranking charities. Here we put *Mieruka's own
prospects* in call order: funders, charities to invite into the pilot, and advisors. That order is John's
outreach plan only: it never appears in the product, is never shown to a charity, and never describes a
charity to donors.

1. **Public filings only.** Use only public filings (IRS Form 990s and exempt-organization list, SEC Form ADV) and organizations' public information. No data from the Mieruka product (donor, family, advisor-account or gift data), ever; nothing here imports the Mieruka product. Families are never listed or looked up.
2. **Keep the source.** Every grant, charity and advisory firm keeps the link to the filing it came from.
3. **A person decides.** Uncertain matches go to review.csv; outreach and personas are a person's call.
4. **No data in git.** Scan results live in `data/` (ignored) or on the server.
5. **Be gentle with the IRS server.** Large windowed reads with a pause between requests.

Run `pytest` before every commit. Python 3.11 or newer.
