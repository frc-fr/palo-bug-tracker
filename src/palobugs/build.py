"""Generate the static site: copy site/ and cross the extracted pages into dist/data/."""
import json
import logging
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .collect import SITE, load_pages
from .extract import read_changes
from .feed import build_feed, latest_changes
from .hardware import hardware_index, load
from .normalize import families_in, family_key, family_of_model, model_key, models_in
from .versions import PRODUCT, branch_key, branch_of, bug_key, train_of, version_key

log = logging.getLogger(__name__)

STATUS_CODES = {"addressed": "r", "known": "k", "limitations": "l"}
SERIES_NAME = "CN-Series"


def is_series(branch: str) -> bool:
    """"10.x": a CN-Series page, true of every branch of that generation of PAN-OS."""
    return branch.endswith(".x")
LATER = r"\b{branch}\.(\d+(?:-h\d+)?)\s+and\s+later"


def load_extracted(directory: Path) -> List[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*/*.json"))]


def read_schedule(path: Path) -> Optional[dict]:
    """The crons of the automatic update, read in sources/schedule.yml so the site cannot contradict it."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    crons = re.findall(r'cron:\s*"([^"]+)"', text)
    timezone_name = re.search(r'timezone:\s*"([^"]+)"', text)
    if not crons:
        return None
    return {"crons": crons, "timezone": timezone_name.group(1) if timezone_name else "UTC"}


def change_release(branch: str, text: str, releases: List[str]) -> str:
    """A change met on upgrade: the release it names ("11.2.3 and later"), else the first of the branch."""
    match = re.search(LATER.format(branch=re.escape(branch)), text)
    if match and f"{branch}.{match.group(1)}" in releases:
        return f"{branch}.{match.group(1)}"
    return releases[0]


def build_data(documents: List[dict], pages_meta: Dict[str, dict], lifecycle: dict, changes_log: List[dict],
               eol: Optional[dict] = None) -> dict:
    """Index and bugs. The releases come from their pages, the facts from the rows of these pages."""
    page_paths = sorted({doc["path"] for doc in documents})
    page_positions = {path: i for i, path in enumerate(page_paths)}
    releases = {doc["version"] for doc in documents if doc["version"]}
    versions = sorted(releases, key=version_key)
    positions = {version: i for i, version in enumerate(versions)}
    by_branch = defaultdict(list)
    for version in versions:
        by_branch[branch_of(version)].append(version)
    first_seen = {}
    for change in changes_log:
        if change["kind"] == "version":
            first_seen.setdefault(change["version"], change["date"])

    bugs: Dict[str, dict] = {}

    def bug_of(bug_id: str) -> dict:
        return bugs.setdefault(bug_id, {"events": {}, "known": None, "fix": None, "workaround": None,
                                         "families": set(), "series_fix": None})

    def add_event(bug: dict, version: str, code: str, page: str, scope: int = 0):
        bug["events"].setdefault((positions[version], code), [positions[version], code, page_positions[page], scope])

    order = {"known": 0, "limitations": 1, "addressed": 2}
    documents = sorted(documents, key=lambda d: (version_key(d["version"]) if d["version"] else (0,), order.get(d["kind"], 3)))
    page_of = defaultdict(dict)
    revised = defaultdict(str)
    branch_pages = defaultdict(dict)
    changes_of = defaultdict(list)
    # "Now resolved, see …": counted only when the Addressed Issues of that release do not list the issue.
    pending = []
    branch_wide = []
    series_pages = {}
    for doc in documents:
        branch = doc["branch"]
        meta = pages_meta.get(doc["path"], {})
        stamp = (meta.get("lastmod") or "")[:10]
        if doc["version"]:
            page_of[doc["version"]][doc["kind"]] = page_positions[doc["path"]]
            revised[doc["version"]] = max(revised[doc["version"]], stamp)
        elif is_series(branch):
            series_pages[page_positions[doc["path"]]] = f"{SERIES_NAME} {branch}"
        elif doc["kind"] in ("limitations", "changes", "known"):
            branch_pages[branch].setdefault(doc["kind"], page_positions[doc["path"]])
        if doc["kind"] == "changes" and by_branch[branch]:
            for feature, text in doc["changes"]:
                version = change_release(branch, f"{feature} {text}", by_branch[branch])
                changes_of[version].append([feature, text, page_positions[doc["path"]]])
        if doc["kind"] not in STATUS_CODES:
            continue
        if is_series(branch):
            generation = branch.split(".")[0]
            mains = [v for v in versions if "-h" not in v and v.split(".")[0] == generation]
        else:
            mains = [v for v in by_branch[branch] if "-h" not in v]
        for issue in doc["issues"]:
            for bug_id in issue["ids"]:
                bug = bug_of(bug_id)
                if doc["kind"] == "addressed":
                    bug["fix"] = issue["description"] or bug["fix"]
                else:
                    bug["known"] = issue["description"] or bug["known"]
                bug["workaround"] = issue["workaround"] or bug["workaround"]
                resolved = issue.get("resolved_in")
                resolved = resolved if resolved in positions else None
                if is_series(branch):
                    bug["families"].add(SERIES_NAME)
                if doc["version"]:
                    add_event(bug, doc["version"], STATUS_CODES[doc["kind"]], doc["path"])
                elif doc["kind"] == "addressed":
                    # CN-Series names no release for its fixes: the fix is told, not placed.
                    bug["series_fix"] = [f"{SERIES_NAME} {branch}", page_positions[doc["path"]]]
                else:
                    branch_wide.append((bug, branch, doc["kind"], resolved, doc["path"], mains))
                if resolved:
                    pending.append((bug, resolved, doc["path"]))

    for bug, resolved, path in pending:
        add_event(bug, resolved, "r", path)
    # A page of the whole branch: true of each release up to the fix, as far as the notes tell.
    # Old branches repeat in it the Known Issues of their releases: those keep their release.
    for bug, branch, kind, resolved, path, mains in branch_wide:
        code = "l" if kind == "limitations" else "k"
        if code == "k" and not is_series(branch) and any(
                versions[event[0]].startswith(f"{branch}.") and event[1] == "k" for event in bug["events"].values()):
            continue
        limit = version_key(train_of(resolved)) if resolved else None
        for version in mains:
            if limit is None or version_key(version) < limit:
                add_event(bug, version, code, path, 1)

    model_names = set()
    family_names = set()
    rows_text = {}
    for bug_id, bug in bugs.items():
        text = f"{bug['known'] or ''} {bug['fix'] or ''} {bug['workaround'] or ''}"
        rows_text[bug_id] = text
        model_names.update(models_in(text))
        family_names.update(families_in(text))
    family_names |= {family_of_model(model) for model in model_names}
    family_names |= {name for bug in bugs.values() for name in bug["families"]}
    families = sorted(family_names, key=family_key)
    family_positions = {name: i for i, name in enumerate(families)}
    models = sorted(model_names, key=model_key)

    rows = []
    # The PAN- issues first, the newest first; the numbers of the other prefixes do not compare with them.
    for bug_id, bug in sorted(bugs.items(), key=lambda item: (bug_key(item[0])[0] != "PAN", -bug_key(item[0])[1], item[0])):
        text = rows_text[bug_id]
        cited = models_in(text)
        named = set(families_in(text)) | {family_of_model(model) for model in cited} | bug["families"]
        description = bug["known"] or bug["fix"] or ""
        fix = bug["fix"] if bug["known"] and bug["fix"] and bug["fix"] != bug["known"] else None
        rows.append([
            bug_id, description, bug["workaround"], cited, sorted(family_positions[name] for name in named),
            sorted(bug["events"].values(), key=lambda event: (event[0], event[1])), fix, bug["series_fix"],
        ])

    index_versions = []
    for version in versions:
        own = page_of.get(version, {})
        index_versions.append({
            "v": version,
            "branch": branch_of(version),
            "hotfix": "-h" in version,
            "released": first_seen.get(version),
            "revised": revised.get(version) or None,
            "addressed": own.get("addressed"),
            "known": own.get("known"),
            "changes": changes_of.get(version, []),
        })
    index = {
        "product": PRODUCT,
        "site": SITE,
        "pages": page_paths,
        "branches": {branch: pages for branch, pages in sorted(branch_pages.items(), key=lambda item: branch_key(item[0]))},
        "series": {str(page): name for page, name in sorted(series_pages.items())},
        "families": families,
        "models": [[model, family_positions[family_of_model(model)]] for model in models],
        "versions": index_versions,
        "lifecycle": lifecycle,
        "hardware": hardware_index(models, eol),
    }
    return {"index": index, "bugs": {"bugs": rows}}


def build_site(extracted: Path, pages_path: Path, changes_path: Path, lifecycle_path: Path, schedule_path: Path,
               sources: Path, dist: Path, base_url: str, hardware_path: Path = Path("sources/hardware.json")) -> dict:
    documents = load_extracted(extracted)
    pages_meta = load_pages(pages_path)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8")) if lifecycle_path.exists() else {"source": None, "branches": {}}
    all_changes = read_changes(changes_path)
    data = build_data(documents, pages_meta, lifecycle, all_changes, load(hardware_path))
    data["index"].update({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schedule": read_schedule(schedule_path),
    })
    changes = latest_changes(all_changes, documents)

    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(sources, dist)
    folder = dist / "data"
    folder.mkdir(parents=True)
    for name, content in (("index.json", data["index"]), ("bugs.json", data["bugs"]), ("changes.json", changes)):
        (folder / name).write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    descriptions = {row[0]: row[1] for row in data["bugs"]["bugs"]}
    (dist / "feed.xml").write_bytes(build_feed(changes, descriptions, base_url))
    rows = data["bugs"]["bugs"]
    return {
        "versions": len(data["index"]["versions"]),
        "hotfixes": sum(1 for v in data["index"]["versions"] if v["hotfix"]),
        "families": len(data["index"]["families"]),
        "models": len(data["index"]["models"]),
        "hardware": len(data["index"]["hardware"]["models"]),
        "bugs": len(rows),
        "with model": sum(1 for row in rows if row[3]),
        "with family": sum(1 for row in rows if row[4]),
    }
