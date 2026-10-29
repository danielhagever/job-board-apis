#!/usr/bin/env python3
"""Rerun every example in README.md and say which still answer the way it says.

Standard library only. One request per check, one second apart, so a full run
asks each host for one or two things and takes about half a minute.

    python3 verify.py
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "job-board-apis-verify/1.0 (+https://github.com/danielhagever/job-board-apis)"

PHENOM_BODY = {
    "lang": "en_global", "deviceType": "desktop", "country": "global",
    "pageName": "search-results", "ddoKey": "refineSearch", "sortBy": "", "subsearch": "",
    "from": 0, "size": 100, "jobs": True, "counts": False,
    "all_fields": ["country", "state", "city", "category", "type"],
    "clearAll": False, "jdsource": "facets", "isSliderEnable": False, "pageId": "page17",
    "siteType": "external", "keywords": "", "global": True, "selected_fields": {},
    "locationData": {}, "sort": {"order": "desc", "field": "postedDate"},
}
WORKDAY = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
ORACLE = ("https://ejwl.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
          "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
          "&finder=findReqs;siteNumber=CX,limit={limit},offset={offset},sortBy=POSTING_DATES_DESC")
ADP = "https://myjobs.adp.com/public/staffing/v1"
# Hosts measured to refuse cloud addresses while answering a home connection:
# careers.rtx.com gave a GitHub Actions runner 403 on 2026-10-25 and a residential
# line 100 rows the same hour. In CI a 403 from these is a skip, not a failure.
CLOUD_BLOCKED = {"Phenom", "Phenom window"}


def fetch(url, body=None, headers=None):
    """(status, raw bytes); HTTP errors come back as their status, not an exception."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, h), timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get_json(url, body=None, headers=None):
    status, raw = fetch(url, body, headers)
    if status != 200:
        raise AssertionError(f"HTTP {status}")
    return json.loads(raw)


def rows(n):
    assert n > 0, "no rows"
    return f"{n} rows"


def greenhouse_pay():
    """Greenhouse returns pay_input_ranges only to a request that asks for them."""
    url = "https://boards-api.greenhouse.io/v1/boards/andurilindustries/jobs"
    plain = get_json(url)["jobs"]
    assert plain and not any("pay_input_ranges" in j for j in plain), "pay without the flag"
    time.sleep(1)
    asked = get_json(url + "?pay_transparency=true")["jobs"]
    priced = [j for j in asked if j.get("pay_input_ranges")]
    assert priced and "min_cents" in priced[0]["pay_input_ranges"][0], "no ranges with the flag"
    return f"{len(priced)} of {len(asked)} priced with the flag, none without"


def phenom_window():
    """Phenom answers while from + size stays under 10,000, then 200 with nothing."""
    url = "https://jobs.cvshealth.com/widgets"
    body = {"ddoKey": "refineSearch", "jobs": True, "size": 100,
            "sort": {"order": "desc", "field": "dateCreated"}}
    inside = get_json(url, dict(body, **{"from": 9899}))["refineSearch"]
    assert inside["totalHits"] > 10000, f"CVS lists {inside['totalHits']}, not past the window"
    rows(len(inside["data"]["jobs"]))
    time.sleep(1)
    past = get_json(url, dict(body, **{"from": 9900}))["refineSearch"]
    assert not (past.get("data") or {}).get("jobs") and past.get("totalHits") == 0, \
        "the window moved"
    return f"{inside['totalHits']} listed, rows at 9,899, none at 9,900"


def oracle_ceiling():
    rows(len(get_json(ORACLE.format(limit=200, offset=9800))["items"][0]["requisitionList"]))
    after = get_json(ORACLE.format(limit=20, offset=9990))["items"][0].get("requisitionList") or []
    assert not after, f"{len(after)} rows past 10,000: the ceiling moved"
    return "rows at offset 9,800, none at 9,990"


def workday_limit():
    status, _ = fetch(WORKDAY, {"limit": 50, "offset": 0, "searchText": "", "appliedFacets": {}})
    assert status == 400, f"limit 50 answered {status}: the cap moved"
    return "limit 50 refused with 400"


def workday_wrap():
    """Past offset 2,000 Workday answers page one again instead of nothing."""
    first = get_json(WORKDAY, {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}})
    time.sleep(1)
    past = get_json(WORKDAY, {"limit": 20, "offset": 2000, "searchText": "", "appliedFacets": {}})
    a = [j["externalPath"] for j in first["jobPostings"]]
    b = [j["externalPath"] for j in past["jobPostings"]]
    assert b and a == b, "offset 2000 no longer repeats page one"
    return "offset 2000 answers page one again"


def workday_total():
    first = get_json(WORKDAY, {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}})
    second = get_json(WORKDAY, {"limit": 20, "offset": 20, "searchText": "", "appliedFacets": {}})
    return f"total {first['total']} on page one, {second['total']} on page two"


def successfactors():
    """EY's SuccessFactors table: a printed total, 25 jobs, each linked twice."""
    status, raw = fetch("https://careers.ey.com/search-jobs/?q=&startrow=0")
    assert status == 200, f"HTTP {status}"
    page = raw.decode("utf-8", "replace")
    total = re.search(r"of <b>([0-9,]+)</b>", page)
    assert total, "no printed total"
    links = re.findall(r'/job/[^"]*/([0-9]+)/', page)
    assert links and len(links) == 2 * len(set(links)), \
        f"{len(links)} links for {len(set(links))} jobs: no longer printed twice"
    return f"total {total.group(1)}, {len(set(links))} jobs, each linked twice"


def adp():
    org = get_json(f"{ADP}/career-site/pbna")["orgoid"]
    d = get_json(f"{ADP}/job-requisitions?careerSiteDomain=pbna&$top=100&$skip=0",
                 headers={"orgoid": org})
    return f"count {d['count']}, {rows(len(d['jobRequisitions']))}"


def adp_count_cap():
    """`count` says 10,000 and the list still answers past it."""
    time.sleep(5)    # ADP answers a burst of quick pages with HTML instead of JSON
    org = get_json(f"{ADP}/career-site/popeyes")["orgoid"]
    d = get_json(f"{ADP}/job-requisitions?careerSiteDomain=popeyes&$top=100&$skip=10000"
                 "&$select=reqId", headers={"orgoid": org})
    n = len(d["jobRequisitions"])
    assert d["count"] == 10000 and n > 0, f"count {d['count']}, {n} rows past it"
    return f"count {d['count']}, {rows(n)} at $skip=10000"


BRASSRING = "https://sjobs.brassring.com"


def _brassring_search():
    """Best Buy's BrassRing search: (opener, headers with the token, first page of jobs)."""
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    h = {"User-Agent": UA}
    with opener.open(urllib.request.Request(
            f"{BRASSRING}/TGnewUI/Search/Home/Home?partnerid=25632&siteid=5649", None, h),
            timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    token = re.search(r'__RequestVerificationToken" type="hidden" value="([^"]*)', page)
    assert token, "no token on the search page"
    h = dict(h, RFT=token.group(1), **{"Content-Type": "application/json"})
    body = {"PartnerId": "25632", "SiteId": "5649", "Keyword": "", "Location": "",
            "KeywordCustomSolrFields": "JobTitle", "LocationCustomSolrFields": "Location"}
    req = urllib.request.Request(
        f"{BRASSRING}/TgNewUI/Search/Ajax/MatchedJobs", json.dumps(body).encode(), h)
    with opener.open(req, timeout=60) as r:
        return opener, h, json.loads(r.read())


def brassring():
    """Best Buy's BrassRing search: the page's cookie and token, then JSON."""
    _, _, d = _brassring_search()
    return f"count {d['JobsCount']}, {rows(len(d['Jobs']['Job']))}"


def brassring_details():
    """One Best Buy job's details: the posting's sections and the pay questions."""
    opener, h, d = _brassring_search()
    job = d["Jobs"]["Job"][0]
    reqid = next(q["Value"] for q in job["Questions"] if q.get("QuestionName") == "reqid")
    time.sleep(1)
    body = {"partnerId": "25632", "siteId": "5649", "jobid": reqid, "configMode": "",
            "jobSiteId": "5649", "turnOffHttps": False}
    req = urllib.request.Request(
        f"{BRASSRING}/TgNewUI/Search/Ajax/JobDetails", json.dumps(body).encode(), h)
    with opener.open(req, timeout=60) as r:
        qs = json.loads(r.read())["ServiceResponse"]["Jobdetails"]["JobDetailQuestions"]
    assert qs, "no JobDetailQuestions"
    pay = [q["QuestionName"] for q in qs if re.search(r"pay|salar|rate", str(q.get("QuestionName")), re.I)]
    return f"{len(qs)} questions, pay questions {pay}"


def rippling_record():
    """Barry's Rippling board: an entry per place, and each job's record has the pay."""
    base = "https://api.rippling.com/platform/api/ats/v1/board/barrys-careers/jobs"
    jobs = get_json(base)
    uuids = {j["uuid"] for j in jobs}
    assert len(uuids) < len(jobs), "the list no longer repeats a job per place"
    time.sleep(1)
    rec = get_json(f"{base}/{jobs[0]['uuid']}")
    assert "payRangeDetails" in rec and isinstance(rec.get("description"), dict), \
        "the record lost payRangeDetails or its two-part description"
    return f"{len(jobs)} entries for {len(uuids)} jobs, record carries payRangeDetails"


def bamboohr_record():
    """A BambooHR job's own record: the date and the compensation line the list lacks."""
    h = "https://eggharborcafe.bamboohr.com/careers"
    first = get_json(f"{h}/list")["result"][0]["id"]
    time.sleep(1)
    job = get_json(f"{h}/{first}/detail")["result"]["jobOpening"]
    assert "compensation" in job and job.get("datePosted"), "the record lost its date or pay line"
    return f"datePosted {job['datePosted']}, compensation {job['compensation']!r}"


def _job_posting(url):
    """The schema.org JobPosting on a job page, or None."""
    page = fetch(url)[1].decode("utf-8", "replace")
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob, strict=False)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    return None


def jazzhr():
    """CentiMark's JazzHR board: an HTML list, a JobPosting on each job's page."""
    status, raw = fetch("https://centimark.applytojob.com/apply")
    assert status == 200, f"HTTP {status}"
    links = re.findall(r'href="(https://centimark\.applytojob\.com/apply/[A-Za-z0-9]+/[^"]+)"',
                       raw.decode("utf-8", "replace"))
    assert links, "no job links on the board"
    for url in dict.fromkeys(links[:5]):
        time.sleep(1)
        jp = _job_posting(url)
        if jp:
            return f"{len(set(links))} jobs listed, JobPosting dated {jp.get('datePosted')}"
    raise AssertionError("no JobPosting on the first job pages")


def radancy_pay():
    """CommonSpirit Health's Radancy site fills baseSalary, unlike UnitedHealth's."""
    status, raw = fetch("https://www.commonspirit.careers/sitemap.xml")
    assert status == 200, f"sitemap HTTP {status}"
    jobs = re.findall(r"<loc>([^<]*/job/[^<]*)</loc>", raw.decode("utf-8", "replace"))
    assert jobs, "no job pages in the sitemap"
    for url in jobs[:3]:
        time.sleep(1)
        value = ((_job_posting(url) or {}).get("baseSalary") or {}).get("value") or {}
        if any(isinstance(value.get(k), (int, float)) for k in ("minValue", "maxValue", "value")):
            return f"baseSalary {value.get('minValue')} - {value.get('maxValue')} {value.get('unitText')}"
    raise AssertionError("no filled baseSalary on the first job pages")


def radancy():
    """UnitedHealth's Radancy site: search closed, sitemap open, JSON-LD per job."""
    status, raw = fetch("https://careers.unitedhealthgroup.com/robots.txt")
    assert status == 200 and b"Disallow:/search-jobs/" in raw.replace(b" ", b""), \
        "robots.txt no longer closes /search-jobs/"
    status, raw = fetch("https://careers.unitedhealthgroup.com/sitemap.xml")
    assert status == 200, f"sitemap HTTP {status}"
    jobs = re.findall(r"<loc>([^<]*/job/[^<]*)</loc>", raw.decode("utf-8", "replace"))
    assert jobs, "no job pages in the sitemap"
    time.sleep(1)
    status, raw = fetch(jobs[0])
    page = raw.decode("utf-8", "replace")
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert ld and json.loads(ld.group(1), strict=False).get("@type") == "JobPosting", \
        "no JobPosting on a job page"
    return f"{len(jobs)} jobs in the sitemap, JobPosting on the page"


CHECKS = [
    ("Greenhouse", lambda: rows(len(get_json(
        "https://boards-api.greenhouse.io/v1/boards/figma/jobs")["jobs"]))),
    ("Greenhouse pay", greenhouse_pay),
    ("Lever", lambda: rows(len(get_json(
        "https://api.lever.co/v0/postings/palantir?mode=json")))),
    ("Ashby", lambda: rows(len(get_json(
        "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true")["jobs"]))),
    ("Recruitee", lambda: rows(len(get_json(
        "https://bunq.recruitee.com/api/offers/")["offers"]))),
    ("Workable", lambda: rows(len(get_json(
        "https://apply.workable.com/api/v1/widget/accounts/huzzle?details=true")["jobs"]))),
    ("Rippling", lambda: rows(len(get_json(
        "https://api.rippling.com/platform/api/ats/v1/board/rippling/jobs")))),
    ("Personio", lambda: rows(fetch(
        "https://thermondo.jobs.personio.de/xml")[1].count(b"<position>"))),
    ("Breezy HR", lambda: rows(len(get_json(
        "https://thirdchannel-inc.breezy.hr/json")))),
    ("Teamtailor", lambda: rows(len(get_json(
        "https://anicuraglobal.teamtailor.com/jobs.json")["items"]))),
    ("BambooHR", lambda: rows(len(get_json(
        "https://401auto.bamboohr.com/careers/list")["result"]))),
    ("Workday", lambda: rows(len(get_json(
        WORKDAY, {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}})["jobPostings"]))),
    ("Workday limit", workday_limit),
    ("Workday total", workday_total),
    ("Workday wrap", workday_wrap),
    ("Oracle", lambda: rows(len(get_json(
        ORACLE.format(limit=200, offset=0))["items"][0]["requisitionList"]))),
    ("Oracle ceiling", oracle_ceiling),
    ("ADP", adp),
    ("ADP count cap", adp_count_cap),
    ("Phenom", lambda: rows(len(get_json(
        "https://careers.rtx.com/widgets", PHENOM_BODY)["refineSearch"]["data"]["jobs"]))),
    ("Phenom window", phenom_window),
    ("Jibe", lambda: rows(len(get_json(
        "https://careers.costco.com/api/jobs?page=1&limit=100")["jobs"]))),
    ("Eightfold", lambda: rows(len(get_json(
        "https://hp.eightfold.ai/api/pcsx/search?domain=hp.com&query=&location=&start=0")
        ["data"]["positions"]))),
    ("SAP SuccessFactors", successfactors),
    ("BrassRing", brassring),
    ("BrassRing details", brassring_details),
    ("Rippling record", rippling_record),
    ("BambooHR record", bamboohr_record),
    ("JazzHR", jazzhr),
    ("Radancy", radancy),
    ("Radancy pay", radancy_pay),
    ("Amazon", lambda: rows(len(get_json(
        "https://amazon.jobs/en/search.json?offset=0&result_limit=100&sort=recent&base_query=")
        ["jobs"]))),
]


def main():
    failed = skipped = 0
    in_ci = bool(os.environ.get("CI"))
    for name, check in CHECKS:
        try:
            print(f"PASS  {name:16} {check()}")
        except Exception as e:  # report every failure and keep going
            if in_ci and name in CLOUD_BLOCKED and "HTTP 403" in str(e):
                print(f"SKIP  {name:16} 403 to a cloud address; answers from a home connection")
                skipped += 1
                continue
            failed += 1
            print(f"FAIL  {name:16} {type(e).__name__}: {e}")
        sys.stdout.flush()
        time.sleep(1)
    passed = len(CHECKS) - failed - skipped
    print(f"\n{passed} of {len(CHECKS)} pass" + (f", {skipped} skipped" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
