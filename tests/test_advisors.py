"""The advisor list: a made-up SEC file only."""
import csv
import io
import zipfile

from funders import advisors, places
from test_charities import ZCTA

SEC = ("Organization CRD#,SEC#,Primary Business Name,Legal Name,Main Office Street Address 1,Main Office City,"
       "Main Office State,Main Office Postal Code,Main Office Telephone Number,Website Address,5A,5D(a)(1),5D(b)(1),"
       "5D(h)(1),5F(2)(c),Latest ADV Filing Date\n"
       "1001,801-1,LAUREL WEALTH PARTNERS,LAUREL WEALTH PARTNERS LLC,1 MAIN ST,LIGONIER,PA,15658,724-555-0101,"
       "https://www.laurelwealth.example/,12,40,60,3,450000000,03/01/2026\n"
       "1002,801-2,SMALL PLANNING CO,SMALL PLANNING CO,2 MAIN ST,PITTSBURGH,PA,15222,412-555-0102,,3,30,12,0,40000000,02/01/2026\n"
       "1003,802-3,PRIVATE FUND GP,PRIVATE FUND GP,3 MAIN ST,PITTSBURGH,PA,15222,,,2,0,0,0,900000000,01/01/2026\n"
       "1004,801-4,PHILLY ADVISERS,PHILLY ADVISERS,4 MAIN ST,PHILADELPHIA,PA,19103,,,9,10,90,1,800000000,01/01/2026\n"
       "1005,801-5,OHIO ADVISERS,OHIO ADVISERS,5 MAIN ST,COLUMBUS,OH,43215,,,9,10,90,1,800000000,01/01/2026\n")


def test_columns_are_found_by_their_form_adv_names():
    col = advisors.find_columns(SEC.splitlines()[0].split(","))
    assert {"crd", "firm", "state", "zip", "aum", "hnw_clients", "charity_clients", "website"} <= set(col)


def test_build_keeps_local_registered_advisers_and_the_list(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ia100226.csv", SEC)
    (tmp_path / "ia100226.zip").write_bytes(buf.getvalue())
    (tmp_path / "targets.csv").write_text(
        "firm,city,area,type,persona,priority,why,angle,src,url\n"
        "Small Planning Co,Pittsburgh,Allegheny,Fee-only RIA,Independent planner,A,Owner reachable,Ask for advice,Directory,https://x\n"
        "Trustmont Advisory Group,Greensburg,Westmoreland,Advisory firm,Independent planner,B,Local,Near you,Unbiased,https://y\n")
    get = lambda url, a=None, b=None: ZCTA.encode()
    res = advisors.build(tmp_path / "ia100226.zip", tmp_path, targets=str(tmp_path / "targets.csv"), get=get,
                         log=lambda m: None)
    rows = {r["firm"]: r for r in csv.DictReader((tmp_path / "advisors.csv").open())}
    assert set(rows) == {"LAUREL WEALTH PARTNERS", "SMALL PLANNING CO", "Trustmont Advisory Group"}   # no ERA, no Philly, no Ohio
    laurel = rows["LAUREL WEALTH PARTNERS"]
    assert laurel["call_order"] == "A" and laurel["county"] == "Westmoreland" and laurel["website"] == "www.laurelwealth.example"
    assert "60 high-net-worth clients" in laurel["call_order_why"] and laurel["iapd"].endswith("/1001")
    small = rows["SMALL PLANNING CO"]
    assert small["call_order"] == "A" and small["on_targets_list"] == "yes" and small["why"] == "Owner reachable"  # list wins
    assert rows["Trustmont Advisory Group"]["list_source"] == "Unbiased"           # kept though the SEC file lacks it
    assert res["list_matched"] == 1 and res["list_only"] == 1


def test_social_pages_are_not_a_firm_website():
    assert advisors._site("https://www.youtube.com/channel/UCv") == ""
    assert advisors._site("www.linkedin.com/company/x") == ""
    assert advisors._site("https://www.Gibsoncapital.com/") == "www.gibsoncapital.com"
    assert advisors._site("https://www.xcelfinancial.com") == "www.xcelfinancial.com"
