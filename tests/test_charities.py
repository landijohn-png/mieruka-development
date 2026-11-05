"""The charity list: made-up charities and filings only."""
import csv

from funders import charities, places
from helpers import FakeIRS, make_zip, NS


def charity_990(ein, name, revenue, gifts, year="2024", restricted=""):
    return (f'<?xml version="1.0" encoding="utf-8"?><Return {NS}><ReturnHeader><TaxPeriodEndDt>{year}-06-30</TaxPeriodEndDt>'
            f"<ReturnTypeCd>990</ReturnTypeCd><Filer><EIN>{ein}</EIN><BusinessName><BusinessNameLine1Txt>{name}"
            f"</BusinessNameLine1Txt></BusinessName><PhoneNum>7245550100</PhoneNum></Filer>"
            f"<BusinessOfficerGrp><PersonNm>ANN CHIEF</PersonNm><PersonTitleTxt>EXECUTIVE DIRECTOR</PersonTitleTxt></BusinessOfficerGrp>"
            f"<TaxYr>{year}</TaxYr></ReturnHeader><ReturnData><IRS990><WebsiteAddressTxt>www.example.org</WebsiteAddressTxt>"
            f"<ActivityOrMissionDesc>FEEDS NEIGHBORS IN NEED</ActivityOrMissionDesc>"
            f"<CYContributionsGrantsAmt>{gifts}</CYContributionsGrantsAmt><CYTotalRevenueAmt>{revenue}</CYTotalRevenueAmt>"
            f"<CYTotalExpensesAmt>{revenue}</CYTotalExpensesAmt>"
            + (f"<NoDonorRestrictionNetAssetsGrp><EOYAmt>999</EOYAmt></NoDonorRestrictionNetAssetsGrp>"
               f"<DonorRestrictionNetAssetsGrp><BOYAmt>5</BOYAmt><EOYAmt>{restricted}</EOYAmt></DonorRestrictionNetAssetsGrp>"
               if restricted else "") +
            "<Form990PartVIISectionAGrp><PersonNm>BOB BOARD</PersonNm><TitleTxt>BOARD MEMBER</TitleTxt></Form990PartVIISectionAGrp>"
            "<Form990PartVIISectionAGrp><PersonNm>DANA GIFTS</PersonNm><TitleTxt>DIRECTOR OF DEVELOPMENT</TitleTxt>"
            "<KeyEmployeeInd>X</KeyEmployeeInd></Form990PartVIISectionAGrp>"
            "<Form990PartVIISectionAGrp><PersonNm>ANN CHIEF</PersonNm><TitleTxt>EXECUTIVE DIRECTOR</TitleTxt>"
            "<OfficerInd>X</OfficerInd></Form990PartVIISectionAGrp>"
            "</IRS990></ReturnData></Return>").encode()


BMF = ("EIN,NAME,ICO,STREET,CITY,STATE,ZIP,GROUP,SUBSECTION,AFFILIATION,CLASSIFICATION,RULING,DEDUCTIBILITY,FOUNDATION,"
       "ACTIVITY,ORGANIZATION,STATUS,TAX_PERIOD,ASSET_CD,INCOME_CD,FILING_REQ_CD,PF_FILING_REQ_CD,ACCT_PD,ASSET_AMT,"
       "INCOME_AMT,REVENUE_AMT,NTEE_CD,SORT_NAME\n"
       "111111111,VALLEY FOOD PANTRY,,1 MAIN,LIGONIER,PA,15658-1234,0,03,3,1,2000,1,15,0,1,01,202406,5,5,01,0,06,1,3000000,3000000,K31,\n"
       "222222222,CITY ARTS CENTER,,2 MAIN,PITTSBURGH,PA,15222,0,03,3,1,2000,1,15,0,1,01,202406,5,5,01,0,06,1,8000000,8000000,A20,\n"
       "333333333,FAMILY FOUNDATION,,3 MAIN,PITTSBURGH,PA,15222,0,03,3,1,2000,1,04,0,1,01,202412,5,5,01,0,06,1,9000000,9000000,T20,\n"
       "444444444,FAR AWAY CHARITY,,4 MAIN,PHILADELPHIA,PA,19103,0,03,3,1,2000,1,15,0,1,01,202406,5,5,01,0,06,1,2000000,2000000,P20,\n"
       "555555555,TINY CLUB,,5 MAIN,LIGONIER,PA,15658,0,03,3,1,2000,1,15,0,1,01,202406,5,5,01,0,06,1,10000,10000,N20,\n")
ZCTA = ("OID_ZCTA5_20|GEOID_ZCTA5_20|NAMELSAD_ZCTA5_20|AREALAND_ZCTA5_20|AREAWATER_ZCTA5_20|MTFCC_ZCTA5_20|CLASSFP_ZCTA5_20|"
        "FUNCSTAT_ZCTA5_20|OID_COUNTY_20|GEOID_COUNTY_20|NAMELSAD_COUNTY_20|AREALAND_COUNTY_20|AREAWATER_COUNTY_20|"
        "MTFCC_COUNTY_20|CLASSFP_COUNTY_20|FUNCSTAT_COUNTY_20|AREALAND_PART|AREAWATER_PART\n"
        "1|15658|ZCTA5 15658|1|0|G|B5|S|2|42129|Westmoreland County|1|0|G|H1|A|900|0\n"
        "1|15658|ZCTA5 15658|1|0|G|B5|S|3|42111|Somerset County|1|0|G|H1|A|100|0\n"
        "1|15222|ZCTA5 15222|1|0|G|B5|S|4|42003|Allegheny County|1|0|G|H1|A|500|0\n"
        "1|19103|ZCTA5 19103|1|0|G|B5|S|5|42101|Philadelphia County|1|0|G|H1|A|500|0\n")


def test_zip_goes_to_the_county_with_most_of_its_land():
    zc = places.zip_to_county(ZCTA, set(places.COUNTIES.values()))
    assert zc["15658"] == "42129" and zc["15222"] == "42003" and "19103" not in zc


def test_bmf_keeps_local_public_charities_in_the_band():
    zc = places.zip_to_county(ZCTA, set(places.COUNTIES.values()))
    got = {r["ein"]: r for r in charities.read_bmf(BMF, zc)}
    assert set(got) == {"111111111", "222222222"}          # not the foundation, not Philadelphia, not the tiny club
    assert got["111111111"]["cause"] == "Food and nutrition" and got["111111111"]["zip"] == "15658"
    kept = charities.read_bmf(BMF, zc, keep={"555555555"})
    assert "555555555" in {r["ein"] for r in kept}        # a charity on the targets list is always kept


def test_build_reads_each_charitys_latest_990(tmp_path):
    archives = {"2025_TEOS_XML_01A": make_zip({"1001_public.xml": charity_990("111111111", "VALLEY FOOD PANTRY", 3000000, 2400000, restricted="250000"),
                                               "1002_public.xml": charity_990("222222222", "CITY ARTS CENTER", 8000000, 800000)})}
    fake = FakeIRS(2025, archives, [("1001", "111111111", "VALLEY FOOD PANTRY", "990", "202406", "2025_TEOS_XML_01A"),
                                    ("1002", "222222222", "CITY ARTS CENTER", "990", "202406", "")])
    fake.files[charities.BMF.format(state="pa")] = BMF.encode()
    fake.files[places.ZCTA_COUNTY] = ZCTA.encode()
    (tmp_path / "targets.csv").write_text("ein,name,priority,why,angle\n22-2222222,City Arts Center,A,Known to John,Ask about a pilot\n")

    def get(url, a=None, b=None):
        if url not in fake.files:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return fake.get(url, a, b)
    res = charities.build(tmp_path, targets=str(tmp_path / "targets.csv"), years=(2025,), get=get, size_of=fake.size,
                          pause=0, log=lambda m: None)
    assert res["charities"] == 2 and res["read"] == 2
    rows = {r["ein"]: r for r in csv.DictReader((tmp_path / "charities.csv").open())}
    pantry, arts = rows["11-1111111"], rows["22-2222222"]
    assert pantry["call_order"] == "A" and "Westmoreland County" in pantry["call_order_why"] and pantry["contributions_share"] == "0.80"
    assert pantry["website"] == "www.example.org" and pantry["phone"] == "(724) 555-0100" and "FEEDS" in pantry["mission"]
    assert pantry["restricted_net_assets"] == "250000" and "$250K in donor-restricted gifts" in pantry["call_order_why"]
    assert arts["restricted_net_assets"] == ""
    assert pantry["filing"].endswith("2025_TEOS_XML_01A.zip#1001_public.xml")
    assert arts["call_order"] == "A" and arts["on_targets_list"] == "yes" and arts["why"] == "Known to John"   # list wins
    assert arts["filing"].endswith("#1002_public.xml")                    # found through the archive's contents
    people = [r for r in csv.DictReader((tmp_path / "charity_contacts.csv").open()) if r["ein"] == "11-1111111"]
    assert [p["name"] for p in people][:2] == ["Ann Chief", "Dana Gifts"]   # signer, then development before the board
    assert len({p["name"] for p in people}) == len(people)
