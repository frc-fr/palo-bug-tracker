"""Turn the cached pages into data/extracted/<branch>/<page>.json and log what changed.

The results are committed: a page is only fetched again when it changed, and
emptying the cache of the CI does not make the next run read every page again.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import report
from .collect import cache_path, load_pages, page_url
from .parser import Page, parse_page
from .versions import PRODUCT, SERIES_NAME, branch_of, bug_key, version_key

log = logging.getLogger(__name__)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def output_path(output: Path, branch: str, path: str) -> Path:
    return output / branch / f"{path.rsplit('/', 1)[-1]}.json"


def write_page(target: Path, path: str, branch: str, page: Page) -> None:
    """One issue per line, so that a revision gives a readable git diff."""
    head = {"path": path, "branch": branch, "kind": page.kind, "title": page.title, "version": page.version,
            "skipped": page.skipped}
    rows = page.issues if page.kind != "changes" else [list(change) for change in page.changes]
    lines = ",\n".join("  " + json.dumps(row, ensure_ascii=False) for row in rows)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'{body}, "{"changes" if page.kind == "changes" else "issues"}": [\n{lines}\n]}}\n', encoding="utf-8")


def issue_ids(issues: List[dict]) -> set:
    return {bug for issue in issues for bug in issue["ids"]}


def change_key(change: dict):
    return change["date"], version_key(change["version"]), change["kind"]


def read_changes(path: Path) -> List[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def write_changes(path: Path, changes: List[dict]) -> None:
    lines = ",\n".join("  " + json.dumps(change, ensure_ascii=False) for change in sorted(changes, key=change_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[\n{lines}\n]\n" if lines else "[]\n", encoding="utf-8")


def page_changes(page: Page, previous: Optional[dict], date: str) -> List[dict]:
    """A new release or hotfix, and the issues Palo Alto Networks adds to a published page."""
    if not page.version or page.kind not in ("addressed", "known"):
        return []
    after = issue_ids(page.issues)
    if previous is None:
        if page.kind == "known":
            return []
        return [{"date": date, "version": page.version, "kind": "version", "bugs": sorted(after, key=bug_key)}]
    added = after - issue_ids(previous.get("issues", []))
    if not added:
        return []
    kind = "fixed_added" if page.kind == "addressed" else "known_added"
    return [{"date": date, "version": page.version, "kind": kind, "bugs": sorted(added, key=bug_key)}]


def extracted_by_path(output: Path) -> Dict[str, dict]:
    return {doc["path"]: doc for doc in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(output.glob("*/*.json")))}


def group_of(path: str) -> str:
    return SERIES_NAME if path.startswith("cn-series/") else PRODUCT


def crossed(documents: Dict[str, dict]) -> Dict[str, List[dict]]:
    """The rules the site applies across pages, where the issues are read but not all their facts are placed."""
    versions = {doc["version"] for doc in documents.values() if doc.get("version")}
    known: Dict[str, set] = {}
    for doc in documents.values():
        if doc["kind"] == "known" and doc.get("version"):
            known.setdefault(branch_of(doc["version"]), set()).update(issue_ids(doc["issues"]))
    found: Dict[str, List[dict]] = {}
    for path, doc in documents.items():
        url = page_url(path)
        if doc["kind"] in ("known", "limitations"):
            elsewhere = [bug for issue in doc["issues"] if issue.get("resolved_in") and issue["resolved_in"] not in versions
                         for bug in issue["ids"]]
            if elsewhere:
                found.setdefault(path, []).append(report.finding(
                    "left_out", "resolved_unplaced", url, doc["title"], sorted(set(elsewhere), key=bug_key),
                    "said resolved in a release that has no page on the site: the fix is not placed"))
        # Old branches repeat in a page of the whole branch the Known Issues of their releases.
        if doc["kind"] == "known" and not doc.get("version") and not doc["branch"].endswith(".x"):
            repeated = issue_ids(doc["issues"]) & known.get(doc["branch"], set())
            if repeated:
                found.setdefault(path, []).append(report.finding(
                    "left_out", "known_repeated", url, doc["title"], sorted(repeated, key=bug_key),
                    "issues the Known Issues of a release of the branch list too: they keep that release"))
    return found


def extract_all(cache: Path, output: Path, changes_path: Path, pages_path: Path, report_path: Path,
                date: Optional[str] = None) -> List[str]:
    """Parse every cached page, write what is read and the processing report; return why the update stops.

    A page is published for what the code reads of it; what it does not read is in the
    report. A page that no longer parses, or loses most of its issues, keeps its last
    reading. The update stops only when too few pages are read (report.PUBLISH_MINIMUM):
    the site then keeps its last version rather than an empty one.

    Without a change log the data is a baseline: nothing tells when the
    releases already published came out, so none is recorded.
    """
    date = date or today()
    baseline = not changes_path.exists()
    changes = read_changes(changes_path)
    before = extracted_by_path(output)
    previous = {d["key"]: d for d in report.load(report_path).get("documents", [])}
    written: Dict[str, dict] = {}
    pages: Dict[str, Tuple[dict, List[dict], Dict[str, set], bool, str]] = {}
    headings: Dict[str, Dict[str, bool]] = {}
    urls: Dict[str, str] = {}
    prose: List[dict] = []
    for path, entry in sorted(load_pages(pages_path).items()):
        source = cache_path(cache, path)
        # A page that left the sitemap is no longer checked; the unlisted books never were in it.
        gone = entry.get("listed") is False and entry.get("lastmod") is not None
        if not source.exists() and not (entry.get("unavailable") or gone):
            continue
        url, old = page_url(path), before.get(path)
        findings: List[dict] = []
        page = None
        if source.exists():
            try:
                page = parse_page(source.read_text(encoding="utf-8"), path)
            except Exception as error:  # A page that breaks the parser must not pass silently.
                findings.append(report.finding("not_understood", "parse_error", url, "", [], f"the parser stops: {error!r}"))
        if entry.get("unavailable"):
            findings.append(report.finding("unreachable", "http", url, "", [],
                                           "the page answers with an error: its last reading stays"))
        elif gone:
            findings.append(report.finding("unreachable", "unlisted", url, "", [],
                                           "the page left the sitemap: no longer checked, its last reading stays"))
        ids = {"vendor": set(), "read": set(), "ruled": set(), "failed": set(), "unaccounted": set()}
        if page:
            findings += page.findings
            ids = page.accounting()
            places: Dict[Tuple[str, str], List[str]] = {}
            for bug in sorted(ids["unaccounted"], key=bug_key):
                places.setdefault(page.listed[bug], []).append(bug)
            for (where_page, where), bugs in places.items():
                findings.append(report.finding("suspect", "unaccounted", where_page, where, bugs,
                                               "issue IDs the page lists that no rule of the code accounts for"))
            count = len(ids["read"])
            had = len(issue_ids(old.get("issues", []))) if old else 0
            if had and not count:
                findings.append(report.finding("suspect", "lost_bugs", url, "", [], f"the page had {had} issues and has none now"))
            elif had and count < (1 - report.DROP_LIMIT) * had:
                findings.append(report.finding("suspect", "drop", url, "", [], f"{count} issues read, {had} before"))
            headings[path] = page.headings
            if page.prose:
                prose.append({"key": path, "title": page.title, "page": url, "count": len(page.prose),
                              "ids": sorted(page.prose, key=bug_key)[:report.EXAMPLES]})
        urls[path] = url
        keep = page is None or any(f["rule"] in ("parse_error", "lost_bugs", "drop") for f in findings)
        if page and not keep:
            target = output_path(output, entry["branch"], path)
            if not baseline:
                changes.extend(page_changes(page, old, date))
            write_page(target, path, entry["branch"], page)
            written[path] = json.loads(target.read_text(encoding="utf-8"))
        title = page.title if page and page.title else (old or {}).get("title") or url
        # "Limitations": a page of a whole branch does not always name it.
        if title != url and entry["branch"] not in title:
            title = f"{title} ({group_of(path)} {entry['branch']})"
        pages[path] = (entry, findings, ids, keep, title)

    entries: List[dict] = []
    groups: Dict[str, dict] = {}
    rules = crossed({**before, **written})
    for path, (entry, findings, ids, keep, title) in pages.items():
        findings = findings + rules.get(path, [])
        old = before.get(path)
        group = group_of(path)
        totals = groups.setdefault(group, {"name": group, "documents": 0, "vendor": 0, "read": 0, "ruled": 0, "failed": 0, "unaccounted": 0})
        totals["documents"] += 1
        for bucket in ("vendor", "read", "ruled", "failed", "unaccounted"):
            totals[bucket] += len(ids[bucket])
        if report.status_of(findings) != "read":
            # The pages record no date of their own reading: a reading already kept keeps its date.
            kept = ((previous.get(path) or {}).get("kept") or "—") if keep and old else None
            entries.append(report.document(path, group, title, page_url(path), findings, ids, previous.get(path), kept))
    for found in entries:
        if found["status"] in report.TO_FIX:
            log.warning("%s: %s %s", found["key"], found["status"], ", ".join(sorted({f["rule"] for f in found["findings"]})))
    order = [PRODUCT, SERIES_NAME]
    summary = report.build(report_path, entries, len(pages), sorted(groups.values(), key=lambda g: order.index(g["name"])),
                           report.unused_sections(headings, urls), prose)
    publication = summary["publication"]
    if not publication["published"]:
        return [f"only {publication['read_share']:.0%} of the pages read, under {publication['minimum']:.0%}: the site keeps its last version"]
    # A blocked extraction must not leave a log describing data that is not published.
    write_changes(changes_path, changes)
    return []
