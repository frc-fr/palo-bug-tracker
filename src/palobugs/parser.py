"""Read one Release Notes page: its kind, its release, and the rows of its tables.

Each page of the Release Notes is one topic: the addressed issues of a release
or a hotfix, the known issues of a release, the limitations or the changes of
default behavior of a branch. The issues sit in a two-column table: the issue
ID, then its description. A known issue fixed since says so under its ID:
"This issue is now resolved. See PAN-OS 11.2.15 Addressed Issues."

Security fixes are left out: the rows without an ID that list CVEs, and the CVE
references of the descriptions.
"""
import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Tuple

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


@dataclass
class Table:
    header: List[str] = field(default_factory=list)
    rows: List[List[List[str]]] = field(default_factory=list)


class TopicParser(HTMLParser):
    """Title and tables of a topic; a cell is a list of text blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.tables: List[Table] = []
        self.paragraphs: List[str] = []
        self._in_title = False
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
                self.tables.append(Table())
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
    skipped: int = 0
    warnings: List[str] = field(default_factory=list)


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


def issue_row(cells: List[List[str]], kind: str, page: Page) -> Optional[dict]:
    """One issue from a row: the ID cell, then the description and its workaround."""
    if len(cells) < 2:
        return None
    head = " ".join(cells[0])
    if head.strip().lower() == "issue id":
        return None
    ids = list(dict.fromkeys(f"{prefix}-{number}" for prefix, number in ISSUE_ID.findall(head) if prefix != "CVE"))
    if not ids and BARE_ID.match(cells[0][0] if cells[0] else ""):
        # 11.1.5 lists "254927" alone: the numbers of that size are PAN- issues.
        ids = [f"PAN-{BARE_ID.match(cells[0][0]).group(1)}"]
    body = [block for cell in cells[1:] for block in cell]
    if not ids:
        if "CVE-" in " ".join(body) or head.strip("—–- ") == "":
            page.skipped += 1
            return None
        page.warnings.append(f"row without issue ID: {head[:60]!r}")
        return None
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
    page = Page(kind=kind, title=title, version=version if kind in ("addressed", "known") else None)
    if not title:
        page.warnings.append("no title")
    for table in parser.tables:
        header = " ".join(table.header).lower()
        if kind == "changes" or ("feature" in header and "change" in header):
            for cells in table.rows:
                if len(cells) >= 2:
                    feature = clean(" ".join(cells[0]))
                    change = clean(" ".join(block for cell in cells[1:] for block in cell))
                    if change:
                        page.changes.append((feature, change))
            continue
        if kind in ("addressed", "known", "limitations"):
            for cells in table.rows:
                issue = issue_row(cells, kind, page)
                if issue:
                    page.issues.append(issue)
    # CN-Series names no release for its fixes: its pages cover a generation, "CN-Series 10.x".
    if kind == "addressed" and not page.version and page.issues and not path.startswith("cn-series/"):
        page.warnings.append(f"no release in the title {title!r}")
    return page
