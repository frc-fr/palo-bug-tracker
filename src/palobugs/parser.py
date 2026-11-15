"""Read one Release Notes page: its kind, its release, and the rows of its tables.

Each page of the Release Notes is one topic: the addressed issues of a release
or a hotfix, the known issues of a release, the limitations or the changes of
default behavior of a branch. The issues sit in a two-column table: the issue
ID, then its description. A known issue fixed since says so under its ID:
"This issue is now resolved. See PAN-OS 11.2.15 Addressed Issues."

Security fixes are left out: the rows without an ID that list CVEs, and the CVE
references of the descriptions.

Every issue ID a table lists ends in one bucket of the processing report: read,
left out by a known rule ("ruled"), or not understood ("failed"). An ID of a table
found in none of them is a silent path of the code: the report calls the page suspect.
"""
import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set, Tuple

from .collect import page_url
from .report import accounting, finding

# "PAN-317755This issue is now resolved", "PAN- 155147", "RLP—146384": the IDs are not always clean.
ISSUE_ID = re.compile(r"\b([A-Z][A-Z0-9]{1,9})\s?[-–—]\s?(\d{3,7})(?!\d)")
VERSION = r"\d+\.\d+\.\d+(?:-h\d+)?"
# A title once reads "PAN-OS 9-1-16-h3 Addressed Issues": dashes stand for the dots there.
RELEASE = re.compile(r"PAN-OS\s+(\d+)[.-](\d+)[.-](\d+)(-h\d+)?\b")
BARE_ID = re.compile(r"^\s*(\d{5,6})\s*$")
RESOLVED = re.compile(rf"(?:now resolved|resolved|fixed|addressed)\b.*?PAN-OS\s+({VERSION})", re.I | re.S)
CVE = re.compile(r"\s*\(?\bCVE-\d{4}-\d{4,}\b\)?")
WORKAROUND = re.compile(r"^\s*Workarounds?\s*:\s*", re.I)
BLOCKS = {"p", "div", "li", "br", "ul", "ol", "dd", "dt", "pre", "h2", "h3", "h4", "table"}
HEADINGS = {"h1", "h2", "h3", "h4"}
# The prefixes of the issue IDs: models (PA-5420) and ciphers (SHA-256) share the shape of an ID.
PREFIXES = "PAN|WF500|PLUG|APL|APPORTAL|CN|DRS|GPC|RLP|WIF"
KNOWN_ID = re.compile(rf"\b({PREFIXES})\s?[-–—]\s?(\d{{3,7}})(?!\d)")
# A cell that starts with an issue ID: what a page lists, even in a form the parser does not read.
LISTED = re.compile(rf"^\W*({PREFIXES})\s?[-–—]\s?(\d{{3,7}})(?!\d)")
# The frame of docs.paloaltonetworks.com, not the topic: never reported as content left unread.
CHROME = re.compile(
    r"^(was this (page|information) helpful|feedback|table of contents|languages?|recommended for you|"
    r"related (documentation|topics)|on this page|download pdf)\b", re.I)
# The rules that leave out a row without ID: a security fix, or an issue Palo Alto Networks names no ID for.
UNNAMED = ("security", "no_id")


@dataclass
class Table:
    header: List[str] = field(default_factory=list)
    rows: List[List[List[str]]] = field(default_factory=list)
    heading: str = ""


class TopicParser(HTMLParser):
    """Title and tables of a topic; a cell is a list of text blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.tables: List[Table] = []
        self.paragraphs: List[str] = []
        # The section titles, in order; a table belongs to the last one.
        self.headings: List[str] = []
        self._in_title = False
        self._in_heading = False
        self._depth = 0
        self._cell: Optional[List[str]] = None
        self._row: Optional[List[List[str]]] = None
        self._header = False
        self._buffer: List[str] = []
        self._item = False
        self._spans: List[bool] = []
        self._after_control = False

    def _flush(self):
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if not text:
            return
        if self._item:
            text = f"• {text}"
            self._item = False
        if self._cell is not None:
            self._cell.append(text)
        elif self._depth == 0 and not self._in_title:
            if self._in_heading:
                self.headings.append(text)
            else:
                self.paragraphs.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "span":
            # A menu path is a run of uicontrol spans, drawn with arrows between them.
            control = "uicontrol" in (dict(attrs).get("class") or "")
            if control and self._after_control:
                self._buffer.append(" > ")
            self._spans.append(control)
            return
        if tag == "h1" and not self.title:
            self._in_title = True
        elif tag == "table":
            self._flush()
            self._depth += 1
            if self._depth == 1:
                self.tables.append(Table(heading=self.headings[-1] if self.headings else self.title))
        elif tag == "tr" and self._depth == 1:
            self._row = []
        elif tag in ("td", "th") and self._depth == 1 and self._row is not None:
            self._flush()
            self._cell = []
            self._header = tag == "th"
        elif tag in BLOCKS:
            self._flush()
            if tag == "li":
                self._item = True
            self._in_heading = tag in HEADINGS

    def handle_endtag(self, tag):
        if tag == "span":
            self._after_control = bool(self._spans) and self._spans.pop()
            return
        self._after_control = False
        if tag == "h1" and self._in_title:
            self.title = " ".join("".join(self._buffer).split())
            self._buffer = []
            self._in_title = False
        elif tag in ("td", "th") and self._depth == 1 and self._cell is not None:
            self._flush()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._depth == 1 and self._row is not None:
            table = self.tables[-1]
            if self._header and not table.rows:
                table.header = [" ".join(cell) for cell in self._row]
            elif any(self._row):
                table.rows.append(self._row)
            self._row = None
            self._header = False
        elif tag == "table":
            self._flush()
            self._depth = max(0, self._depth - 1)
        elif tag in BLOCKS:
            self._flush()
            if tag in HEADINGS:
                self._in_heading = False

    def handle_data(self, data):
        if data.strip():
            self._after_control = False
        self._buffer.append(data)


@dataclass
class Page:
    kind: str  # addressed, known, limitations, changes, other
    title: str
    version: Optional[str]  # the release of an addressed or known page; None for a whole branch
    issues: List[dict] = field(default_factory=list)
    changes: List[Tuple[str, str]] = field(default_factory=list)
    url: str = ""
    # What is not read, and why: a known rule ("left_out"), or a layout to adapt the code to.
    findings: List[dict] = field(default_factory=list)
    # Each issue ID the page lists, with the page and the section that list it.
    listed: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    # Each section title, and whether the site reads something under it.
    headings: Dict[str, bool] = field(default_factory=dict)
    # The issue IDs the text cites outside the tables.
    prose: Set[str] = field(default_factory=set)

    def note(self, kind: str, rule: str, where: str, ids: List[str], detail: str, rows: int = 0) -> None:
        """A finding; `rows` counts the rows without an ID, which a list of IDs cannot count."""
        found = finding(kind, rule, self.url, where, ids, detail)
        found["count"] = len(ids) or rows
        self.findings.append(found)

    @property
    def warnings(self) -> List[str]:
        """What the code cannot read: it has to be adapted."""
        return [as_text(f) for f in self.findings if f["kind"] == "not_understood"]

    @property
    def skipped(self) -> int:
        """The rows left out for want of an ID: security fixes, and issues named by no ID."""
        return sum(f["count"] for f in self.findings if f["rule"] in UNNAMED)

    def accounting(self) -> Dict[str, Set[str]]:
        """Each issue ID the page lists, in one bucket: read, ruled out, failed, or unaccounted."""
        return accounting(set(self.listed), {bug for issue in self.issues for bug in issue["ids"]}, self.findings)


def as_text(found: dict) -> str:
    return f"{found['page']}: {found['count']} issues under {found['where']!r}: {found['detail']}"


def clean(text: str) -> str:
    text = CVE.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)
    return " ".join(text.split())


def kind_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "addressed-issues" in name:
        return "addressed"
    if "known-issues" in name:
        return "known"
    if "limitations" in name:
        return "limitations"
    if "changes-to-default-behavior" in path:
        return "changes"
    return "other"


def listed_in(cells: List[List[str]]) -> List[str]:
    """The ID of a row the parser does not read: its first cell that starts with an issue ID."""
    for cell in cells:
        match = LISTED.match(" ".join(cell))
        if match:
            return [f"{match.group(1)}-{match.group(2)}"]
    return []


def issue_row(cells: List[List[str]], kind: str, page: Page, where: str = "") -> Optional[dict]:
    """One issue from a row: the ID cell, then the description and its workaround."""
    head = " ".join(cells[0]) if cells else ""
    if head.strip().lower() == "issue id":
        return None
    if len(cells) < 2:
        listed = listed_in(cells)
        for bug in listed:
            page.listed.setdefault(bug, (page.url, where))
        if listed:
            page.note("not_understood", "row_unknown", where, listed, "a row with an issue ID and no description")
        return None
    ids = list(dict.fromkeys(f"{prefix}-{number}" for prefix, number in ISSUE_ID.findall(head) if prefix != "CVE"))
    if not ids and BARE_ID.match(cells[0][0] if cells[0] else ""):
        # 11.1.5 lists "254927" alone: the numbers of that size are PAN- issues.
        ids = [f"PAN-{BARE_ID.match(cells[0][0]).group(1)}"]
    body = [block for cell in cells[1:] for block in cell]
    if not ids:
        # An ID in another cell: a layout the code does not read.
        others = listed_in(cells[1:])
        for bug in others:
            page.listed.setdefault(bug, (page.url, where))
        if others or not ("CVE-" in " ".join(body) or head.strip("—–- ") == ""):
            page.note("not_understood", "row_unknown", where, others, f"a row without issue ID in its first cell: {head[:60]!r}", rows=1)
        elif "CVE-" in " ".join(body):
            page.note("left_out", "security", where, [], "a row without issue ID that lists CVEs", rows=1)
        else:
            page.note("left_out", "no_id", where, [], "an issue the page names by no ID", rows=1)
        return None
    # A row read lists the IDs of its first cell; the other cells describe it.
    for bug in ids:
        page.listed.setdefault(bug, (page.url, where))
    description, workaround = [], []
    for block in body:
        if WORKAROUND.match(block) or workaround:
            workaround.append(WORKAROUND.sub("", block))
        else:
            description.append(block)
    resolved = RESOLVED.search(head)
    return {
        "ids": ids,
        "description": clean(" ".join(description)),
        "workaround": clean(" ".join(workaround)) or None,
        "resolved_in": resolved.group(1) if resolved and kind != "addressed" else None,
    }


def parse_page(text: str, path: str) -> Page:
    parser = TopicParser()
    parser.feed(text)
    parser.close()
    title = html.unescape(parser.title)
    kind = kind_of(path)
    release = RELEASE.search(title)
    version = f"{release.group(1)}.{release.group(2)}.{release.group(3)}{release.group(4) or ''}" if release else None
    page = Page(kind=kind, title=title, version=version if kind in ("addressed", "known") else None, url=page_url(path))
    if not title:
        page.note("not_understood", "parse_error", "", [], "the page has no title")
    # The topic itself is read whenever its kind is; its sections when a table under them is.
    headings = {title: kind != "other"} if title else {}
    headings.update({heading: False for heading in parser.headings if heading != title})
    for table in parser.tables:
        where = html.unescape(table.heading)
        header = " ".join(table.header).lower()
        if kind == "changes" or ("feature" in header and "change" in header):
            for cells in table.rows:
                if len(cells) >= 2:
                    feature = clean(" ".join(cells[0]))
                    change = clean(" ".join(block for cell in cells[1:] for block in cell))
                    if change:
                        page.changes.append((feature, change))
                        headings[where] = True
                        continue
                for bug in listed_in(cells):
                    page.listed.setdefault(bug, (page.url, where))
            continue
        if kind in ("addressed", "known", "limitations"):
            for cells in table.rows:
                issue = issue_row(cells, kind, page, where)
                if issue:
                    page.issues.append(issue)
                    headings[where] = True
            continue
        # A table the site does not read: its IDs are counted nowhere.
        for cells in table.rows:
            for bug in listed_in(cells):
                page.listed.setdefault(bug, (page.url, where))
    ids = list(dict.fromkeys(bug for issue in page.issues for bug in issue["ids"]))
    if kind == "addressed" and not page.version and ids:
        if path.startswith("cn-series/"):
            # CN-Series names no release for its fixes: its pages cover a generation, "CN-Series 10.x".
            page.note("left_out", "series_release", title, ids,
                      "CN-Series names no release for its fixes: the site tells the fix without placing it")
        else:
            page.note("not_understood", "release_unknown", title, ids, f"no release in the title {title!r}")
            page.issues = []
    page.headings = {heading: used for heading, used in headings.items() if heading and not CHROME.search(heading)}
    page.prose = {f"{prefix}-{number}" for text in parser.paragraphs + parser.headings
                  for prefix, number in KNOWN_ID.findall(text)} - set(page.listed)
    return page
