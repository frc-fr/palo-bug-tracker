"""Support dates of the PAN-OS branches, from the "End-of-Life Summary" of Palo Alto Networks.

Read when the data is collected, never by the browser. The table "PAN-OS &
Panorama" gives, per branch, its release date, the end of its standard support
and, for some, an extended support. A page that no longer parses keeps the last dates.
"""
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PAGE_URL = "https://www.paloaltonetworks.com/services/support/end-of-life-announcements/end-of-life-summary"
MINIMUM_BRANCHES = 8

TABLE = re.compile(r'<table[^>]*id="pan-os-panorama"[^>]*>(.*?)</table>', re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
BRANCH = re.compile(r"^(\d+\.\d+)$")


def iso(text: str) -> Optional[str]:
    """"July 30th, 2026" or "August 28, 2025"; None for an empty cell."""
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.replace("^", "").replace("+", "")).strip()
    if not text:
        return None
    for layout in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, layout).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"unreadable date {text!r}")


def parse_lifecycle(page: str) -> dict:
    """Return {branch: {released, support, extended}}; raise if the page looks wrong."""
    table = TABLE.search(page)
    if not table:
        raise ValueError("no PAN-OS table in the page")
    branches = {}
    for row in ROW.findall(table.group(1)):
        cells = [html.unescape(re.sub(r"<sup.*?</sup>|<[^>]+>", "", cell, flags=re.S)).replace("\xa0", " ").strip()
                 for cell in CELL.findall(row)]
        match = BRANCH.match(cells[0]) if cells else None
        if not match or len(cells) < 3:
            continue
        support = iso(cells[2])
        if not support:
            continue
        branches[match.group(1)] = {
            "released": iso(cells[1]),
            "support": support,
            "extended": iso(cells[4]) if len(cells) > 4 else None,
        }
    if len(branches) < MINIMUM_BRANCHES:
        raise ValueError(f"only {len(branches)} branches in the lifecycle page")
    return branches


def update_lifecycle(path: Path, client) -> None:
    """Refresh the dates; the Release Notes must not depend on this page."""
    try:
        response = client.request("GET", PAGE_URL)
        response.raise_for_status()
        branches = parse_lifecycle(response.text)
    except (RuntimeError, ValueError, OSError) as error:
        log.error("support dates kept as they were: %s", error)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": PAGE_URL, "branches": branches}, indent=2) + "\n")
