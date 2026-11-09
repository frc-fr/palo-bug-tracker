"""Turn the cached pages into data/extracted/<branch>/<page>.json and log what changed.

The results are committed: a page is only fetched again when it changed, and
emptying the cache of the CI does not make the next run read every page again.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .collect import cache_path, load_pages
from .parser import Page, parse_page
from .versions import bug_key, version_key

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


def extract_all(cache: Path, output: Path, changes_path: Path, pages_path: Path,
                date: Optional[str] = None) -> Dict[str, List[str]]:
    """Parse every cached page and return the warnings per page.

    Without a change log the data is a baseline: nothing tells when the
    releases already published came out, so none is recorded.
    """
    date = date or today()
    baseline = not changes_path.exists()
    changes = read_changes(changes_path)
    problems = {}
    for path, entry in sorted(load_pages(pages_path).items()):
        source = cache_path(cache, path)
        if not source.exists():
            continue
        page = parse_page(source.read_text(encoding="utf-8"), path)
        target = output_path(output, entry["branch"], path)
        previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
        if not baseline:
            changes.extend(page_changes(page, previous, date))
        write_page(target, path, entry["branch"], page)
        if page.warnings:
            problems[path] = page.warnings
    # A failed extraction must not leave a log describing data that is not published.
    if not problems:
        write_changes(changes_path, changes)
    return problems
