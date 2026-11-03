"""Made-up returns and a fake IRS server for tests. No real funder or donor data."""
import io
import zipfile

NS = 'xmlns="http://www.irs.gov/efile"'


def pf_return(ein, name, state, grants, preselected=False, year="2024"):
    rows = "".join(
        f"<GrantOrContributionPdDurYrGrp><RecipientBusinessName><BusinessNameLine1Txt>{r}</BusinessNameLine1Txt>"
        f"</RecipientBusinessName><RecipientUSAddress><StateAbbreviationCd>{s}</StateAbbreviationCd></RecipientUSAddress>"
        f"<GrantOrContributionPurposeTxt>{p}</GrantOrContributionPurposeTxt><Amt>{a}</Amt></GrantOrContributionPdDurYrGrp>"
        for r, s, p, a in grants)
    pre = "<OnlyContriToPreselectedInd>X</OnlyContriToPreselectedInd>" if preselected else ""
    return (f'<?xml version="1.0" encoding="utf-8"?><Return {NS}><ReturnHeader><TaxPeriodEndDt>{year}-12-31</TaxPeriodEndDt>'
            f"<ReturnTypeCd>990PF</ReturnTypeCd><Filer><EIN>{ein}</EIN><BusinessName><BusinessNameLine1Txt>{name}"
            f"</BusinessNameLine1Txt></BusinessName><USAddress><StateAbbreviationCd>{state}</StateAbbreviationCd></USAddress>"
            f"</Filer><TaxYr>{year}</TaxYr></ReturnHeader><ReturnData><IRS990PF><SupplementaryInformationGrp>{pre}{rows}"
            f"</SupplementaryInformationGrp></IRS990PF></ReturnData></Return>").encode()


def sched_i_return(ein, name, state, grants, year="2024"):
    rows = "".join(
        f"<RecipientTable><RecipientBusinessName><BusinessNameLine1Txt>{r}</BusinessNameLine1Txt></RecipientBusinessName>"
        f"<RecipientEIN>{e}</RecipientEIN><USAddress><StateAbbreviationCd>{s}</StateAbbreviationCd></USAddress>"
        f"<CashGrantAmt>{a}</CashGrantAmt><PurposeOfGrantTxt>{p}</PurposeOfGrantTxt></RecipientTable>"
        for r, e, s, p, a in grants)
    return (f'<?xml version="1.0" encoding="utf-8"?><Return {NS}><ReturnHeader><TaxPeriodEndDt>{year}-06-30</TaxPeriodEndDt>'
            f"<ReturnTypeCd>990</ReturnTypeCd><Filer><EIN>{ein}</EIN><BusinessName><BusinessNameLine1Txt>{name}"
            f"</BusinessNameLine1Txt></BusinessName><USAddress><StateAbbreviationCd>{state}</StateAbbreviationCd></USAddress>"
            f"</Filer><TaxYr>{year}</TaxYr></ReturnHeader><ReturnData><IRS990><CYTotalRevenueAmt>1</CYTotalRevenueAmt></IRS990>"
            f"<IRS990ScheduleI>{rows}</IRS990ScheduleI></ReturnData></Return>").encode()


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(f"2025_TEOS_XML_01A/{name}", body)
    return buf.getvalue()


class FakeIRS:
    """Serves an index, a downloads page and archives from memory, honoring byte ranges."""

    def __init__(self, year, archives: dict[str, bytes], index_rows: list[tuple]):
        self.files = {}
        base = f"https://apps.irs.gov/pub/epostcard/990/xml/{year}/"
        for batch, data in archives.items():
            self.files[base + f"{batch}.zip"] = data
        idx = "RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,TAXPAYER_NAME,RETURN_TYPE,DLN,OBJECT_ID,XML_BATCH_ID\n"
        idx += "".join(f"1,EFILE,{e},{tp},2025,{n},{rt},1,{oid},{b}\n" for oid, e, n, rt, tp, b in index_rows)
        self.files[base + f"index_{year}.csv"] = idx.encode()
        links = "".join(f'<a href="{base}{b}.zip">{b}</a>' for b in archives)
        self.files["https://www.irs.gov/charities-non-profits/form-990-series-downloads"] = links.encode()
        self.requests = 0

    def get(self, url, start=None, end=None):
        self.requests += 1
        data = self.files[url]
        if start is None:
            return data
        return data[start:(len(data) if end is None else end + 1)]

    def size(self, url):
        return len(self.files[url])
