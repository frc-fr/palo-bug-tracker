"""Hardware status: the "Hardware End-of-Life Dates" page of Palo Alto Networks.

Read when the data is collected, never by the browser. One row per product
reaching its end of sale, with its end of life date and the last PAN-OS
release that supports it. Only the rows naming a firewall or an appliance are
kept: a card, a disk or a transceiver says nothing of the model it goes into,
and the other products (Prisma SD-WAN ION, LightCyber) do not run PAN-OS.

Palo Alto Networks publishes its preferred releases on a page reserved for
customers: the site, which needs no account, does not use it.

A page that no longer parses keeps the last values.
"""
import html
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from .lifecycle import iso
from .normalize import family_of_model, model_key, models_in

log = logging.getLogger(__name__)

PAGE_URL = "https://www.paloaltonetworks.com/services/support/end-of-life-announcements/hardware-end-of-life-dates"
MINIMUM_ANNOUNCEMENTS = 15

TABLE = re.compile(r"<table.*?</table>", re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
PAN_OS = re.compile(r"PAN-OS\s+(\d+\.\d+)")
# A system SKU names its chassis: PAN-PA-7080-AC-SYS is a PA-7080; PA-820-ZTP a PA-820.
SYSTEM_SUFFIX = re.compile(r"(?<=\d)(?:-(?:AC|DC))?-(?:SYS|ZTP)\b")


def cell_text(cell: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).replace("\xa0", " ").split())


def product_models(product: str) -> List[str]:
    """The firewalls and appliances a product cell names, without their cards or spare parts."""
    text = SYSTEM_SUFFIX.sub("", product.replace("PAN-PA-", "PA-"))
    return models_in(text)


def date(text: str) -> Optional[str]:
    return iso(re.sub(r"\(.*?\)", "", text))


def parse_hardware(page: str) -> List[dict]:
    found = []
    for table in TABLE.findall(page):
        for row in ROW.findall(table)[1:]:
            cells = [cell_text(cell) for cell in CELL.findall(row)]
            if len(cells) < 5:
                continue
            product, end_of_sale, end_of_life, last_os = cells[0], cells[1], cells[2], cells[4]
            branches = PAN_OS.findall(last_os)
            models = product_models(product)
            # Other products of the page do not run PAN-OS, as "LightCyber Magna Master (M-100)".
            if not models or (not branches and "TBD" not in last_os):
                continue
            # The M-100 gives one release per memory size: the larger one is its last.
            last = max(branches, key=lambda b: tuple(map(int, b.split(".")))) if branches else None
            found.append({
                "product": product,
                "models": models,
                "end_of_sale": date(end_of_sale),
                "end_of_life": date(end_of_life),
                "last_software": last,
                "page": PAGE_URL,
            })
    return found


def write_lines(path: Path, head: dict, key: str, items: List[dict]) -> None:
    """One item per line, for readable diffs."""
    lines = ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in items)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    path.write_text(f'{body}, "{key}": [\n{lines}\n]}}\n', encoding="utf-8")


def update_hardware(path: Path, client) -> None:
    """Refresh the end of life dates; a page that no longer parses keeps them as they were."""
    try:
        response = client.request("GET", PAGE_URL)
        response.raise_for_status()
        announcements = parse_hardware(response.text)
        if len(announcements) < MINIMUM_ANNOUNCEMENTS:
            raise ValueError(f"only {len(announcements)} hardware announcements")
    except (RuntimeError, ValueError, OSError) as error:
        log.error("hardware end of life kept as it was: %s", error)
        return
    write_lines(path, {"source": PAGE_URL}, "announcements", announcements)


def load(path: Path) -> Optional[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def hardware_index(cited: List[str], eol: Optional[dict]) -> dict:
    """The models of the Hardware tab: those the notes cite and those of an announcement.

    The shape is that of juni-bug-tracker, so the browser code stays the same:
    an announcement is [variants, bulletin, last software, end of support, page],
    here with the model as its only variant and no bulletin.
    """
    announcements = (eol or {}).get("announcements", [])
    models = set(cited) | {model for a in announcements for model in a["models"]}
    entries = {
        model: {
            "cited": model in cited,
            "family": family_of_model(model),
            "eol": [[[model], None, a["last_software"], a["end_of_life"], a["page"]] for a in announcements if model in a["models"]],
            "suggested": [],
        }
        for model in sorted(models, key=model_key)
    }
    return {"eol_source": (eol or {}).get("source"), "suggested_source": None, "as_of": None, "general": [], "models": entries}
