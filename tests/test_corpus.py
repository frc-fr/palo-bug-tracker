"""Checks on the real pages; skipped when .cache/html is empty."""
import os
from pathlib import Path

import pytest

from palobugs.collect import cache_path, cached_pages
from palobugs.parser import parse_page

CACHE = Path(os.environ.get("PALOBUGS_CACHE", ".cache/html"))
PAGES = list(cached_pages(CACHE)) if CACHE.exists() else []
pytestmark = pytest.mark.corpus


def read(path: str):
    return parse_page(cache_path(CACHE, path).read_text(encoding="utf-8"), path)


@pytest.mark.skipif(not PAGES, reason="no cached page")
@pytest.mark.parametrize("path", PAGES)
def test_every_page_parses_cleanly(path):
    page = read(path)
    assert not page.warnings
    assert page.title
    text = " ".join(f"{i['description']} {i['workaround'] or ''}" for i in page.issues)
    assert "CVE-" not in text and "â€" not in text


def test_known_facts_of_11_2_13():
    hotfix = "pan-os/11-2/pan-os-release-notes/pan-os-11-2-13-known-and-addressed-issues/pan-os-11-2-13-h3-addressed-issues"
    known = "pan-os/11-2/pan-os-release-notes/pan-os-11-2-13-known-and-addressed-issues/pan-os-11-2-13-known-issues"
    if not (cache_path(CACHE, hotfix).exists() and cache_path(CACHE, known).exists()):
        pytest.skip("11.2.13 not cached")
    fixes = {bug: issue for issue in read(hotfix).issues for bug in issue["ids"]}
    assert fixes["PAN-338608"]["description"].startswith("(PA-5420 firewalls only) Fixed an issue where OSPFv3")
    issues = {bug: issue for issue in read(known).issues for bug in issue["ids"]}
    assert issues["PAN-326677"]["resolved_in"] == "11.2.15"
    assert issues["WF500-6271"]["workaround"] == "Gracefully restart the affected Wildfire cluster nodes."
