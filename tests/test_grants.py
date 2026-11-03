from funders import grants as G
from helpers import pf_return, sched_i_return


def test_pf_grants_and_totals():
    x = pf_return("111111111", "EXAMPLE FAMILY FOUNDATION", "PA",
                  [("CHARITY NAVIGATOR", "NJ", "GENERAL SUPPORT", 20000), ("LOCAL PANTRY", "PA", "FOOD", 5000),
                   ("CITY LIBRARY", "OH", "BOOKS", 1000)], preselected=True)
    rg = G.read([x[:100], x[100:]], keep=lambda g: "NAVIGATOR" in g.recipient)
    assert rg.funder_ein == "111111111" and rg.funder_state == "PA" and rg.return_type == "990PF"
    assert rg.tax_year == "2024" and rg.preselected_only is True
    assert [g.recipient for g in rg.grants] == ["CHARITY NAVIGATOR"]
    assert rg.total_paid == 26000 and rg.median_grant == 5000 and rg.recipient_states == {"NJ", "PA", "OH"}


def test_schedule_i_grants():
    x = sched_i_return("222222222", "EXAMPLE CHARITABLE GIFT FUND", "MA",
                       [("CANDID", "131837418", "NY", "GENERAL", 50000)])
    rg = G.read([x])
    assert rg.return_type == "990" and rg.preselected_only is None
    assert rg.grants[0].recipient_ein == "131837418" and rg.grants[0].amount == 50000


def test_has_grants():
    assert G.has_grants(b"<RecipientTable>") and not G.has_grants(b"<IRS990>")
