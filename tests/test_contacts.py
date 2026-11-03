import csv
import json

from funders import contacts
from helpers import FakeIRS, make_zip, NS

PF = (f'<?xml version="1.0" encoding="utf-8"?><Return {NS}><ReturnHeader><ReturnTypeCd>990PF</ReturnTypeCd>'
      "<Filer><EIN>111111111</EIN><BusinessName><BusinessNameLine1Txt>EXAMPLE FAMILY FOUNDATION</BusinessNameLine1Txt></BusinessName>"
      "<PhoneNum>4125551234</PhoneNum><USAddress><AddressLine1Txt>9 HOME LANE</AddressLine1Txt><StateAbbreviationCd>PA</StateAbbreviationCd></USAddress></Filer>"
      "<BusinessOfficerGrp><PersonNm>JANE DOE</PersonNm><PersonTitleTxt>PRESIDENT</PersonTitleTxt><PhoneNum>4125550000</PhoneNum></BusinessOfficerGrp>"
      "<TaxYr>2024</TaxYr></ReturnHeader><ReturnData><IRS990PF>"
      "<OfficerDirTrstKeyEmplInfoGrp><OfficerDirTrstKeyEmplGrp><PersonNm>JANE DOE</PersonNm><TitleTxt>PRESIDENT</TitleTxt>"
      "<USAddress><AddressLine1Txt>9 HOME LANE</AddressLine1Txt></USAddress></OfficerDirTrstKeyEmplGrp>"
      "<OfficerDirTrstKeyEmplGrp><PersonNm>JOHN ROE</PersonNm><TitleTxt>TRUSTEE</TitleTxt></OfficerDirTrstKeyEmplGrp></OfficerDirTrstKeyEmplInfoGrp>"
      "<StatementsRegardingActyGrp><WebsiteAddressTxt>www.examplefamily.org</WebsiteAddressTxt></StatementsRegardingActyGrp>"
      "<SupplementaryInformationGrp><ApplicationSubmissionInfoGrp><RecipientPersonNm>PAT GRANTS</RecipientPersonNm>"
      "<RecipientUSAddress><AddressLine1Txt>1 GRANT ST</AddressLine1Txt><CityNm>PITTSBURGH</CityNm><StateAbbreviationCd>PA</StateAbbreviationCd>"
      "<ZIPCd>15222</ZIPCd></RecipientUSAddress><RecipientPhoneNum>4125559999</RecipientPhoneNum>"
      "<RecipientEmailAddressTxt>grants@examplefamily.org</RecipientEmailAddressTxt>"
      "<FormAndInfoAndMaterialsTxt>LETTER OF INQUIRY, TWO PAGES</FormAndInfoAndMaterialsTxt>"
      "<SubmissionDeadlinesTxt>MARCH 1 AND SEPTEMBER 1</SubmissionDeadlinesTxt>"
      "<RestrictionsOnAwardsTxt>WESTERN PENNSYLVANIA ONLY</RestrictionsOnAwardsTxt></ApplicationSubmissionInfoGrp>"
      "<GrantOrContributionPdDurYrGrp><RecipientBusinessName><BusinessNameLine1Txt>CANDID</BusinessNameLine1Txt></RecipientBusinessName>"
      "<Amt>1000</Amt></GrantOrContributionPdDurYrGrp></SupplementaryInformationGrp></IRS990PF></ReturnData></Return>").encode()


def test_read_contacts_from_a_foundation_return():
    c = contacts.read_contacts([PF[:300], PF[300:]])
    assert c["phone"] == "(412) 555-1234" and c["website"] == "www.examplefamily.org" and c["preselected_only"] is False
    g = c["grants"][0]
    assert g["name"] == "Pat Grants" and g["email"] == "grants@examplefamily.org" and g["phone"] == "(412) 555-9999"
    assert g["address"] == "1 GRANT ST, PITTSBURGH, PA 15222" and "LETTER OF INQUIRY" in g["materials"]
    assert c["signer"]["name"] == "Jane Doe" and [o["name"] for o in c["officers"]] == ["Jane Doe", "John Roe"]


def test_build_writes_contacts_without_officer_home_addresses(tmp_path):
    fake = FakeIRS(2025, {"B": make_zip({"202501_public.xml": PF})}, [])
    out = tmp_path
    url = "https://apps.irs.gov/pub/epostcard/990/xml/2025/B.zip"
    (out / "funders.csv").write_text("priority,funder,ein,persona\n90,EXAMPLE FAMILY FOUNDATION,11-1111111,1\n80,PASS,22-2222222,pass-through\n")
    (out / "funders.jsonl").write_text(json.dumps({"funder_ein": "111111111", "tax_period_end": "2024-12-31",
                                                   "source": url + "#202501_public.xml"}) + "\n")
    res = contacts.build(out, get=fake.get, size_of=fake.size, pause=0, log=lambda m: None)
    assert res["read"] == 1 and res["grants_contacts"] == 1 and res["with_email"] == 1
    rows = list(csv.DictReader((out / "contacts.csv").open()))
    assert {r["kind"] for r in rows} == {"grants contact", "signer", "officer"}
    assert not any("HOME LANE" in r["address"] for r in rows)
    info = list(csv.DictReader((out / "funder_info.csv").open()))[0]
    assert info["website"] == "www.examplefamily.org" and info["deadlines"] == "MARCH 1 AND SEPTEMBER 1"
