"""Keep sources/pages.json up to date and fetch the Release Notes pages.

Palo Alto Networks publishes its Release Notes on docs.paloaltonetworks.com, one
HTML page per release and per hotfix. Its robots.txt forbids robots on the PDF
copies (/content/dam/techdocs/en_US/*.pdf) but not on these pages, which are
rendered by the server. The sitemap lists them with their date of change: a
page is only fetched when it is new or when that date changed.

The books of the branches missing from the sitemap, as 9.0 and 10.0, ended long
ago: their pages are found once by following the links of the book, and never
checked again.
"""
import hashlib
import json
import logging
import re
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from xml.etree import ElementTree

import requests

log = logging.getLogger(__name__)

SITE = "https://docs.paloaltonetworks.com/"
SITEMAP_URL = f"{SITE}sitemap.xml"
USER_AGENT = "palo-bug-tracker/0.1 (+https://github.com/frc-fr/palo-bug-tracker)"
CRAWL_DELAY = 2.0
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# The book of a branch: pan-os/11-2/pan-os-release-notes up to 11.2, ngfw/release-notes/12-1 since.
BOOK = re.compile(r"^(pan-os/(\d+)-(\d+)/pan-os-release-notes|ngfw/release-notes/(\d+)-(\d+))(?=/|$)")
FIRST_BRANCH = (8, 1)
# CN-Series publishes one page of known and one of addressed issues per generation of PAN-OS:
# "CN-Series 10.x" covers the 10.0, 10.1 and 10.2 branches. Its copies at the root of the book are older.
SERIES = re.compile(r"^cn-series/release-notes/cn-series-(\d+)-x-release-notes/(?:known|addressed)-issues-in-cn-series-\d+-x$")
# Books absent from the sitemap, found by their links.
UNLISTED_BOOKS = {"9.0": "pan-os/9-0/pan-os-release-notes", "10.0": "pan-os/10-0/pan-os-release-notes"}
TOPICS = ("addressed-issues", "known-issues", "limitations", "changes-to-default-behavior")
# Pages crossed to find the topics in an unlisted book; they hold no issue themselves.
HUBS = ("release-information",)
LINK = re.compile(r'href="/content/techdocs/en_US/([^"#?]+?)\.html')
CONTENT_START = '<div class="book-pdf-content">'
CONTENT_END = ("<!-- DOCS-1561", '<div class="btm-pagination">')


class Client:
    """HTTP client that spaces out requests and retries transient failures."""

    def __init__(self, delay: float = CRAWL_DELAY, retries: int = 4):
        self.delay = delay
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def request(self, method: str, url: str) -> requests.Response:
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=90)
            except requests.RequestException as error:
                log.warning("%s %s failed: %s", method, url, error)
            else:
                if response.status_code not in (429, 500, 502, 503, 504):
                    return response
                log.warning("%s %s returned %s", method, url, response.status_code)
            time.sleep(self.delay * 2 ** (attempt + 1))
        raise RuntimeError(f"{method} {url}: giving up after {self.retries} attempts")


def branch_of_path(path: str) -> Optional[str]:
    """"11.2" for a page of the 11.2 book, "10.x" for a CN-Series page; None outside the Release Notes books."""
    series = SERIES.match(path)
    if series:
        return f"{series.group(1)}.x"
    match = BOOK.match(path)
    if not match:
        return None
    major, minor = (match.group(2), match.group(3)) if match.group(2) else (match.group(4), match.group(5))
    if (int(major), int(minor)) < FIRST_BRANCH:
        return None
    return f"{major}.{minor}"


def is_topic(path: str) -> bool:
    """A page that can hold issues or changes; the parent "known and addressed" pages hold none."""
    name = path.rsplit("/", 1)[-1]
    if "/changes-to-default-behavior/" in path:
        # 8.1 splits its changes in one page per area: app-id-changes, networking-changes…
        return True
    return any(topic in name for topic in TOPICS) and not name.endswith("known-and-addressed-issues")


def page_url(path: str) -> str:
    return SITE + path


def cache_path(cache: Path, path: str) -> Path:
    return cache / f"{path}.html"


def load_pages(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    return {entry["path"]: entry for entry in json.loads(path.read_text(encoding="utf-8"))["pages"]}


def save_pages(path: Path, pages: Dict[str, dict]) -> None:
    """One page per line, so that a run gives a readable git diff."""
    entries = sorted(pages.values(), key=lambda entry: entry["path"])
    lines = ",\n".join("  " + json.dumps(entry, ensure_ascii=False) for entry in entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"sitemap": "{SITEMAP_URL}", "pages": [\n{lines}\n]}}\n', encoding="utf-8")


def parse_sitemap(xml: bytes) -> Dict[str, Optional[str]]:
    """The Release Notes topics of the sitemap, with their date of change."""
    found = {}
    for url in ElementTree.fromstring(xml).iter(f"{SITEMAP_NS}url"):
        loc = url.findtext(f"{SITEMAP_NS}loc", "").strip()
        if not loc.startswith(SITE):
            continue
        path = loc[len(SITE):].strip("/")
        if branch_of_path(path) and is_topic(path):
            found[path] = url.findtext(f"{SITEMAP_NS}lastmod")
    return found


def content_of(page: str) -> str:
    """The text of the topic, without the navigation that makes up most of a page."""
    start = page.find(CONTENT_START)
    if start < 0:
        raise ValueError("no topic in the page")
    ends = [page.find(marker, start) for marker in CONTENT_END]
    ends = [end for end in ends if end > 0]
    return page[start:min(ends) if ends else len(page)]


def links_of(page: str, book: str) -> List[str]:
    return sorted({path for path in LINK.findall(page) if path.startswith(book + "/") or path == book})


def crawl_book(book: str, client: Client) -> List[str]:
    """Topics of a book missing from the sitemap, found by following its links."""
    queue, seen, topics = deque([book]), {book}, []
    while queue:
        path = queue.popleft()
        response = client.request("GET", page_url(path))
        if response.status_code != 200:
            log.warning("%s: %s", path, response.status_code)
            continue
        for link in links_of(response.content.decode("utf-8", errors="replace"), book):
            name = link.rsplit("/", 1)[-1]
            if link in seen or not (is_topic(link) or any(hub in name for hub in HUBS) or name.endswith("addressed-issues")):
                continue
            seen.add(link)
            if is_topic(link):
                topics.append(link)
            queue.append(link)
    return sorted(set(topics))


def update_pages(path: Path, client: Client, sitemap: Optional[bytes] = None) -> Dict[str, dict]:
    """Record the topics of the sitemap and of the unlisted books, with their date of change."""
    pages = load_pages(path)
    if sitemap is None:
        response = client.request("GET", SITEMAP_URL)
        response.raise_for_status()
        sitemap = response.content
    listed = parse_sitemap(sitemap)
    if len(listed) < 500:
        raise RuntimeError(f"only {len(listed)} Release Notes pages in the sitemap")
    for page, entry in pages.items():
        if entry.get("listed") and page not in listed:
            # Left in place: its data stays, only no longer checked.
            log.warning("%s: no longer in the sitemap", page)
            entry["listed"] = False
    for page, lastmod in listed.items():
        entry = pages.setdefault(page, {"path": page, "branch": branch_of_path(page)})
        if entry.get("lastmod") != lastmod and "fetched" in entry:
            log.info("%s: changed on %s", page, lastmod)
        entry.update({"listed": True, "lastmod": lastmod})
    for branch, book in UNLISTED_BOOKS.items():
        if any(entry["branch"] == branch for entry in pages.values()):
            continue
        for page in crawl_book(book, client):
            pages.setdefault(page, {"path": page, "branch": branch, "listed": False, "lastmod": None})
    save_pages(path, pages)
    return pages


def due(entry: dict) -> bool:
    """Never fetched, or changed since: an unlisted page is fetched once."""
    if "fetched" not in entry:
        return True
    return bool(entry.get("listed")) and entry.get("fetched_lastmod") != entry.get("lastmod")


def fetch_pages(pages: Dict[str, dict], cache: Path, client: Client, today: str, save=None) -> List[str]:
    """Fetch the pages due into the cache; return their paths."""
    fetched = []
    for path in sorted(p for p, entry in pages.items() if due(entry)):
        entry = pages[path]
        response = client.request("GET", page_url(path))
        if response.status_code != 200:
            log.error("%s: %s", path, response.status_code)
            entry["unavailable"] = True
            continue
        # The server names no charset: requests would read the UTF-8 pages as Latin-1.
        content = content_of(response.content.decode("utf-8", errors="replace"))
        target = cache_path(cache, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        entry.pop("unavailable", None)
        entry.update({"fetched": today, "fetched_lastmod": entry.get("lastmod"),
                      "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
        fetched.append(path)
        log.info("%s: fetched (%d/%d)", path, len(fetched), sum(1 for e in pages.values() if due(e)) + len(fetched))
        # Saved as it goes: a long first run that stops keeps what it fetched.
        if save and len(fetched) % 25 == 0:
            save()
    return fetched


def cached_pages(cache: Path) -> Iterable[str]:
    return sorted(str(p.relative_to(cache))[:-5] for p in cache.rglob("*.html"))
