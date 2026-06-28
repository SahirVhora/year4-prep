#!/usr/bin/env python3
"""
Weekly scraper: discovers Year 4 PiXL arithmetic test PDFs from UK school websites.
Outputs data/maths.json consumed by index.html.

Run:  python3 scrape_papers.py
Cron: 0 8 * * 0  cd ~/projects/uk-education/year4-prep && python3 scrape_papers.py
"""

import json
import os
import re
import sys
import time
import hashlib
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# --- Config ---
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "maths.json")
SEARCH_DELAY = 2  # seconds between searches
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; Year4ArithmeticScraper/1.0; +https://github.com/SahirVhora)"

# ---- Known school sites that reliably host PiXL papers ----
# Each source: base URL, files list, optional referer, optional url_suffix
KNOWN_SOURCES = [
    # Elfrida Primary - Packs 1-6 (S3, needs referer)
    {
        "base": "https://primarysite-prod-sorted.s3.amazonaws.com/elfrida-primary-school-king-alfred-federation/UploadedDocument",
        "referer": "https://www.elfridaprimary.org.uk/",
        "files": [
            ("9e3f336553a543e0b5646224aaab2500", "year-4-arithmetic-test-1.pdf", "Spring", "PiXL Pack 1"),
            ("b740b9e0504840e38d320a3877bf57ba", "year-4-arithmetic-test-2.pdf", "Spring", "PiXL Pack 2"),
            ("99ed9745aeb143edbedc70d985fd1b7f", "year-4-arithmetic-test-3.pdf", "Spring", "PiXL Pack 3"),
            ("484d2e00e5c24553bb764b9b8485654b", "year-4-arithmetic-test-4.pdf", "Summer", "PiXL Pack 4"),
            ("866af9690af84c0ab1138f24ed308b35", "year-4-arithmetic-test-5.pdf", "Summer", "PiXL Pack 5"),
            ("dce73aa251244fb387c1490fb9fa6be7", "year-4-arithmetic-test-6.pdf", "Summer", "PiXL Pack 6"),
        ],
        "school": "Elfrida Primary School",
    },
    # Swingate - Summer Term
    {
        "base": "https://www.swingate.medway.sch.uk/attachments/download.asp?file=",
        "url_suffix": "&type=pdf",
        "files": [
            ("491", "Year 4 Arithmetic Test 1", "Summer", "Swingate Primary School"),
            ("492", "Year 4 Arithmetic Test 2", "Summer", "Swingate Primary School"),
            ("493", "Year 4 Arithmetic Test 3", "Summer", "Swingate Primary School"),
            ("494", "Year 4 Arithmetic Test 4", "Summer", "Swingate Primary School"),
            ("495", "Year 4 Arithmetic Test 5", "Summer", "Swingate Primary School"),
            ("496", "Year 4 Arithmetic Test 6", "Summer", "Swingate Primary School"),
        ],
        "school": "Swingate Primary School",
    },
    # Corsham Regis - Spring Term
    {
        "base": "https://corshamregis.wilts.sch.uk/wp-content/uploads",
        "files": [
            ("2021/01/Arithmetic-Test-1-Y4-Spring.pdf", "Year 4 Arithmetic Test 1", "Spring", "Corsham Regis Primary School"),
            ("2021/02/Arithmetic-Test-4-Y4-Spring.pdf", "Year 4 Arithmetic Test 4", "Spring", "Corsham Regis Primary School"),
            ("2021/02/Arithmetic-Test-5-Y4-Spring.pdf", "Year 4 Arithmetic Test 5", "Spring", "Corsham Regis Primary School"),
        ],
        "school": "Corsham Regis Primary School",
    },
    # Archbishop Courtenay
    {
        "base": "https://www.archbishopcourtenay.org.uk/_site/data/files/migrated",
        "files": [
            ("friday---29012021/arithmetic-test-4-y4-autumn.pdf", "PiXL Arithmetic Test 4", "Autumn", "Archbishop Courtenay Primary School"),
            ("50321/arithmetic-test-7-y4-spring.pdf", "Arithmetic Test 7", "Spring", "Archbishop Courtenay Primary School"),
        ],
        "school": "Archbishop Courtenay Primary School",
    },
    # Full packs (absolute URLs)
    {
        "base": "",
        "files": [
            ("https://www.st-clares.leics.sch.uk/wp-content/uploads/sites/9/2021/02/Year-4-Arithmetic-Tests.pdf", "Complete Year 4 Arithmetic Pack (10 tests)", "All", "St Clare's Primary School"),
            ("https://churchfieldsjunior.com/wp-content/uploads/2020/04/Y4_Arithmetic_Test_10.pdf", "Year 4 Arithmetic Test 10", "Summer", "Churchfields Junior School"),
            ("https://www.primet.lancs.sch.uk/attachments/download.asp?file=2775&type=pdf", "Year 4 Arithmetic Set 4", "Summer", "Primet Primary School"),
        ],
        "school": "Various",
        "is_absolute": True,
    },
]

# Search queries for DuckDuckGo
SEARCH_QUERIES = [
    "year 4 arithmetic test pixl primary PDF site:sch.uk",
    '"arithmetic test" "year 4" pixl PDF',
    'year 4 "arithmetic test" summer term pixl',
    'year 4 "arithmetic test" spring term pixl',
    'year 4 "arithmetic test" autumn term pixl',
    '"year 4 arithmetic" test paper pixl primary',
]


def fetch_url(url, timeout=REQUEST_TIMEOUT, referer=None):
    """Fetch a URL, return (status_code, size_bytes, error_msg)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = referer.rstrip("/")
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            return resp.status, len(content), None
    except HTTPError as e:
        return e.code, 0, str(e)
    except URLError as e:
        return 0, 0, str(e.reason)
    except Exception as e:
        return 0, 0, str(e)


def search_ddgs(query, max_results=8):
    """Search DuckDuckGo using the ddgs CLI. Returns list of {title, href, body}."""
    import subprocess
    try:
        result = subprocess.run(
            ["ddgs", "text", "-q", query, "-m", str(max_results), "-o", "json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  DDGS search warning: {e}", file=sys.stderr)
    return []


def extract_term_from_text(text):
    """Try to determine term from text content."""
    text_lower = text.lower()
    if "summer" in text_lower:
        return "Summer"
    if "spring" in text_lower:
        return "Spring"
    if "autumn" in text_lower:
        return "Autumn"
    return "Unknown"


def extract_test_number(name):
    """Extract test number from filename/name."""
    match = re.search(r'test[_\s-]*(\d+)', name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'pack[_\s-]*(\d+)', name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def verify_pdf(url, referer=None):
    """Verify a PDF URL is accessible and is actually a PDF."""
    status, size, error = fetch_url(url, referer=referer)
    if error:
        return {"status": "broken", "error": error}
    if status != 200:
        return {"status": "broken", "error": f"HTTP {status}"}
    if size < 5000:
        return {"status": "broken", "error": f"Too small ({size} bytes)"}
    if size > 10_000_000:
        return {"status": "broken", "error": f"Too large ({size} bytes)"}
    return {"status": "ok", "size": size}


def discover_from_searches():
    """Discover new papers via DuckDuckGo searches."""
    discovered = []
    seen_urls = set()

    for query in SEARCH_QUERIES:
        print(f"  Searching: {query[:70]}...")
        results = search_ddgs(query, max_results=8)
        for r in results:
            url = r.get("href", "")
            if not url or not url.endswith(".pdf"):
                continue
            if url in seen_urls:
                continue
            # Only include if it looks like Year 4 arithmetic
            text = (r.get("title", "") + " " + r.get("body", "")).lower()
            if "year 4" not in text and "y4" not in text:
                continue
            if "arithmetic" not in text:
                continue

            seen_urls.add(url)
            term = extract_term_from_text(text)
            test_num = extract_test_number(r.get("title", ""))
            school = "Unknown"
            # Try to extract school from URL
            school_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
            if school_match:
                school = school_match.group(1).replace(".sch.uk", "").replace(".org.uk", "").replace(".com", "")

            discovered.append({
                "url": url,
                "name": r.get("title", "Untitled")[:120],
                "term": term,
                "test_number": test_num,
                "school": school,
                "source": "search",
            })
        time.sleep(SEARCH_DELAY)

    return discovered


def discover_from_known_sources():
    """Build paper entries from known school sources."""
    papers = []
    for source in KNOWN_SOURCES:
        school = source["school"]
        referer = source.get("referer")
        for entry in source["files"]:
            if source.get("is_absolute"):
                url = entry[0]
                name = entry[1]
                term = entry[2]
                paper_school = entry[3] if len(entry) > 3 else school
                test_num = extract_test_number(name)
                paper_referer = None
            else:
                file_id = entry[0]
                name = entry[1]
                term = entry[2]
                paper_school = entry[3] if len(entry) > 3 else school
                test_num = extract_test_number(name)
                suffix = source.get("url_suffix", "")
                # If base ends with '=' it's a query-string URL (e.g. download.asp?file=)
                # Otherwise it's a path-based URL (needs / separator)
                if source["base"].endswith("="):
                    url = f"{source['base']}{file_id}{suffix}"
                else:
                    url = f"{source['base']}/{file_id}{suffix}"
                paper_referer = referer

            papers.append({
                "url": url,
                "name": name,
                "term": term,
                "test_number": test_num,
                "school": paper_school,
                "source": "known",
                "_referer": paper_referer,
            })
    return papers


def main():
    print(f"=== PiXL Year 4 Paper Scraper ===  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load existing data to preserve first_seen dates
    existing_by_url = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
            for p in existing.get("papers", []):
                existing_by_url[p["url"]] = p
            print(f"  Loaded {len(existing_by_url)} existing papers from {OUTPUT_FILE}")
        except Exception as e:
            print(f"  Warning: could not load existing data: {e}")

    all_papers = []

    # 1. Known sources (fast, reliable)
    print("[1/2] Checking known school sources...")
    known = discover_from_known_sources()
    print(f"  Found {len(known)} papers from known sources")

    # 2. Search for new papers
    print("[2/2] Searching for new papers...")
    searched = discover_from_searches()
    print(f"  Found {len(searched)} new papers from search")

    # Merge: known sources take priority, searched papers fill gaps
    seen_urls = set()
    for p in known:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            all_papers.append(p)

    for p in searched:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            all_papers.append(p)

    # Verify each PDF
    print()
    print(f"[Verify] Checking {len(all_papers)} PDFs...")
    verified = []
    unverified = []
    broken = []
    new_count = 0
    for i, paper in enumerate(all_papers):
        print(f"  [{i+1}/{len(all_papers)}] {paper['name'][:60]}...", end=" ")
        referer = paper.pop("_referer", None)

        # Preserve or set first_seen
        existing = existing_by_url.get(paper["url"])
        if existing and existing.get("first_seen"):
            paper["first_seen"] = existing["first_seen"]
        else:
            paper["first_seen"] = today
            new_count += 1

        result = verify_pdf(paper["url"], referer=referer)
        if result["status"] == "ok":
            paper["size_bytes"] = result["size"]
            paper["verified"] = True
            verified.append(paper)
            is_new = paper["first_seen"] == today
            print(f"OK ({result['size']:,} bytes){' [NEW]' if is_new else ''}")
        elif "403" in str(result.get("error", "")) or "Forbidden" in str(result.get("error", "")):
            # S3/CloudFront blocks non-browser requests but links work in browsers
            paper["verified"] = False
            paper["error"] = result["error"]
            paper["note"] = "May require browser download (S3/CloudFront restriction)"
            unverified.append(paper)
            print(f"UNVERIFIED (browser-only): {result['error']}")
        else:
            paper["verified"] = False
            paper["error"] = result["error"]
            broken.append(paper)
            print(f"BROKEN: {result['error']}")
        time.sleep(0.3)

    # Sort: by term (Summer first), then by test number
    term_order = {"Summer": 0, "Spring": 1, "Autumn": 2, "All": 3, "Unknown": 4}

    def sort_key(p):
        return (term_order.get(p.get("term", "Unknown"), 5), p.get("test_number") or 99)

    all_good = verified + unverified
    all_good.sort(key=sort_key)
    verified.sort(key=sort_key)

    # Compute content hash for change detection
    payload = json.dumps(all_good, sort_keys=True, default=str)
    content_hash = hashlib.sha256(payload.encode()).hexdigest()[:12]

    # Build output
    output = {
        "metadata": {
            "lastScraped": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "totalPapers": len(all_good),
            "verifiedPapers": len(verified),
            "unverifiedPapers": len(unverified),
            "brokenPapers": len(broken),
            "newPapers": new_count,
            "contentHash": content_hash,
        },
        "papers": all_good,
    }

    if broken:
        output["broken"] = broken

    # Atomic write
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    tmp_path = OUTPUT_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(output, f, indent=2)
    os.replace(tmp_path, OUTPUT_FILE)

    print()
    print(f"=== Done ===")
    print(f"  Verified:   {len(verified)} papers")
    print(f"  Unverified: {len(unverified)} papers (browser-only)")
    print(f"  Broken:     {len(broken)} papers (removed from output)")
    print(f"  New today:  {new_count} papers")
    print(f"  Output:     {OUTPUT_FILE}")
    print(f"  Hash:       {content_hash}")

    # Summary by term
    terms = {}
    for p in all_good:
        t = p.get("term", "Unknown")
        terms[t] = terms.get(t, 0) + 1
    for t, count in sorted(terms.items(), key=lambda x: term_order.get(x[0], 5)):
        print(f"    {t}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
