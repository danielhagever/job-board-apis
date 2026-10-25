#!/usr/bin/env python3
"""Rerun every example in README.md and say which still answer the way it says.

Standard library only. One request per check, one second apart, so a full run
asks each host for one or two things and takes about half a minute.

    python3 verify.py
"""
import json
import os
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
CLOUD_BLOCKED = {"Phenom"}


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


def oracle_ceiling():
    rows(len(get_json(ORACLE.format(limit=200, offset=9800))["items"][0]["requisitionList"]))
    after = get_json(ORACLE.format(limit=20, offset=9990))["items"][0].get("requisitionList") or []
    assert not after, f"{len(after)} rows past 10,000: the ceiling moved"
    return "rows at offset 9,800, none at 9,990"


def workday_limit():
    status, _ = fetch(WORKDAY, {"limit": 50, "offset": 0, "searchText": "", "appliedFacets": {}})
    assert status == 400, f"limit 50 answered {status}: the cap moved"
    return "limit 50 refused with 400"


def workday_total():
    first = get_json(WORKDAY, {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}})
    second = get_json(WORKDAY, {"limit": 20, "offset": 20, "searchText": "", "appliedFacets": {}})
    return f"total {first['total']} on page one, {second['total']} on page two"


def adp():
    org = get_json(f"{ADP}/career-site/pbna")["orgoid"]
    d = get_json(f"{ADP}/job-requisitions?careerSiteDomain=pbna&$top=100&$skip=0",
                 headers={"orgoid": org})
    return f"count {d['count']}, {rows(len(d['jobRequisitions']))}"


CHECKS = [
    ("Greenhouse", lambda: rows(len(get_json(
        "https://boards-api.greenhouse.io/v1/boards/figma/jobs")["jobs"]))),
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
    ("Oracle", lambda: rows(len(get_json(
        ORACLE.format(limit=200, offset=0))["items"][0]["requisitionList"]))),
    ("Oracle ceiling", oracle_ceiling),
    ("ADP", adp),
    ("Phenom", lambda: rows(len(get_json(
        "https://careers.rtx.com/widgets", PHENOM_BODY)["refineSearch"]["data"]["jobs"]))),
    ("Jibe", lambda: rows(len(get_json(
        "https://careers.costco.com/api/jobs?page=1&limit=100")["jobs"]))),
    ("Eightfold", lambda: rows(len(get_json(
        "https://hp.eightfold.ai/api/pcsx/search?domain=hp.com&query=&location=&start=0")
        ["data"]["positions"]))),
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
