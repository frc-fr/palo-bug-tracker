"""Unit checks of the collection, the parser and the crossing of the facts."""
from palobugs import build, collect, extract, lifecycle, normalize, parser
from palobugs.versions import bug_key, train_of, version_key

TABLE = """<div class="book-pdf-content"><div class="topic">
<h1 class="title">{title}</h1>
<table class="table"><thead><tr class="row"><th class="entry"><div class="p">Issue ID</div></th>
<th class="entry"><div class="p">Description</div></th></tr></thead><tbody>{rows}</tbody></table>
</div></div><!-- DOCS-1561 Usabilla -->"""


def row(head, *blocks):
    body = "".join(f'<div class="p">{block}</div>' for block in blocks)
    return f'<tr class="row"><td class="entry">{head}</td><td class="entry">{body}</td></tr>'


def page(title, *rows):
    return TABLE.format(title=title, rows="".join(rows))


def test_versions_order_hotfixes_after_their_release():
    assert sorted(["11.2.13-h3", "11.2.14", "11.2.13", "11.2.13-h10"], key=version_key) == \
        ["11.2.13", "11.2.13-h3", "11.2.13-h10", "11.2.14"]
    assert train_of("11.2.13-h3") == "11.2.13"
    assert sorted(["PAN-99999", "PAN-100000", "WF500-6271"], key=bug_key) == ["PAN-99999", "PAN-100000", "WF500-6271"]


def test_addressed_page_leaves_security_fixes_out():
    text = page(
        "PAN-OS 11.2.13-h3 Addressed Issues",
        row("<b>—</b>", "Fixes were made to address the following CVEs:<ul><li>CVE-2026-0322</li></ul>"),
        row("<b>PAN-338608</b>", "(PA-5420 firewalls only) Fixed an issue where OSPFv3 routes (CVE-2026-1234) were lost."),
    )
    result = parser.parse_page(text, "pan-os/11-2/pan-os-release-notes/x/pan-os-11-2-13-h3-addressed-issues")
    assert (result.kind, result.version, result.skipped, result.warnings) == ("addressed", "11.2.13-h3", 1, [])
    assert result.issues == [{"ids": ["PAN-338608"], "description": "(PA-5420 firewalls only) Fixed an issue where OSPFv3 routes were lost.",
                              "workaround": None, "resolved_in": None}]


def test_known_page_reads_workaround_and_resolution():
    text = page(
        "PAN-OS 11.2.13 Known Issues",
        row('<div class="p"><b>PAN-326677</b></div><div class="p"><tt>This issue is now resolved. See </tt>'
            '<a href="/x">PAN-OS 11.2.15 Addressed Issues</a>.</div>', "Panorama can report a push as successful."),
        row("<b>PAN- 155147</b>", "Commit fails.", "<b>Workaround:</b> Commit again from <span class=\"ph uicontrol\">Device</span>"
            "<span class=\"ph uicontrol\">Setup</span>."),
        row("<b>RLP—146384</b>", "Pods restart."),
    )
    result = parser.parse_page(text, "pan-os/11-2/pan-os-release-notes/x/pan-os-11-2-13-known-issues")
    assert result.warnings == []
    first, second, third = result.issues
    assert first["ids"] == ["PAN-326677"] and first["resolved_in"] == "11.2.15"
    assert second["ids"] == ["PAN-155147"] and second["workaround"] == "Commit again from Device > Setup."
    assert third["ids"] == ["RLP-146384"]


def test_glued_id_is_still_found():
    text = page("PAN-OS 12.1.2 Known Issues", row("PAN-317755This issue is now resolved. See PAN-OS 12.1.4-h7 Addressed Issues.", "x"))
    result = parser.parse_page(text, "ngfw/release-notes/12-1/x/pan-os-12-1-2-known-issues")
    assert result.issues[0]["ids"] == ["PAN-317755"] and result.issues[0]["resolved_in"] == "12.1.4-h7"


def test_typos_of_the_notes():
    bare = parser.parse_page(page("PAN-OS 11.1.5 Addressed Issues", row("254927", "Fixed.")), "x/pan-os-11-1-5-addressed-issues")
    assert bare.issues[0]["ids"] == ["PAN-254927"] and not bare.warnings
    dashed = parser.parse_page(page("PAN-OS 9-1-16-h3 Addressed Issues", row("PAN-1234", "Fixed.")), "x/pan-os-9-1-16-h3-addressed-issues")
    assert dashed.version == "9.1.16-h3"


def test_changes_of_default_behavior():
    text = TABLE.format(title="Changes to Default Behavior in PAN-OS 11.2", rows=row("IKE version", "IKEv2 by default.")).replace(
        "Issue ID", "Feature").replace("Description", "Change")
    result = parser.parse_page(text, "pan-os/11-2/pan-os-release-notes/changes-to-default-behavior/changes-to-default-behavior-in-pan-os-11-2")
    assert result.kind == "changes" and result.changes == [("IKE version", "IKEv2 by default.")]


def test_hardware_names():
    assert normalize.models_in("(PA-5420 firewalls only) on PA-5400 Series and WF500-6271") == ["PA-5420"]
    assert normalize.families_in("PA-5400 Series, PA-7000 and VM-Series") == ["PA-5400 Series", "PA-7000 Series", "VM-Series"]
    assert normalize.models_in("PA-455-5G, PA-450R-5G, M-700, WF-500") == ["M-700", "PA-450R-5G", "PA-455-5G", "WF-500"]
    assert normalize.family_of_model("PA-455-5G") == "PA-400 Series"
    assert normalize.family_of_model("PA-5450") == "PA-5450 Series"
    assert normalize.family_of_model("M-600") == "M-Series"


def test_sitemap_keeps_the_topics_of_the_release_notes():
    xml = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/a/pan-os-11-2-1-known-issues</loc><lastmod>2026-11-06</lastmod></url>
    <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-1-known-and-addressed-issues</loc></url>
    <url><loc>https://docs.paloaltonetworks.com/pan-os/8-0/pan-os-release-notes/pan-os-8-0-1-addressed-issues</loc></url>
    <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/12-1/limitations/limitations-in-pan-os-12-1</loc></url>
    <url><loc>https://docs.paloaltonetworks.com/pan-os/8-1/pan-os-release-notes/x/changes-to-default-behavior/app-id-changes</loc></url>
    <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-admin/known-issues</loc></url>
    </urlset>"""
    assert collect.parse_sitemap(xml) == {
        "pan-os/11-2/pan-os-release-notes/a/pan-os-11-2-1-known-issues": "2026-11-06",
        "ngfw/release-notes/12-1/limitations/limitations-in-pan-os-12-1": None,
        "pan-os/8-1/pan-os-release-notes/x/changes-to-default-behavior/app-id-changes": None,
    }


def test_a_page_is_fetched_when_new_or_changed():
    assert collect.due({"listed": True, "lastmod": "a"})
    assert not collect.due({"listed": True, "lastmod": "a", "fetched": "d", "fetched_lastmod": "a"})
    assert collect.due({"listed": True, "lastmod": "b", "fetched": "d", "fetched_lastmod": "a"})
    assert not collect.due({"listed": False, "lastmod": None, "fetched": "d", "fetched_lastmod": None})


def test_content_drops_the_navigation():
    html = '<nav>menu</nav><div class="book-pdf-content"><h1>T</h1></div><!-- DOCS-1561 x --><footer>f</footer>'
    assert collect.content_of(html) == '<div class="book-pdf-content"><h1>T</h1></div>'


def test_lifecycle_table():
    rows = "".join(f"<tr><td>{v}</td><td>{r}</td><td>{s}</td><td>&nbsp;</td><td>{e}</td></tr>" for v, r, s, e in [
        ("12.1", "August 28, 2025", "August 28, 2028", "August 28, 2029"), ("11.0", "November 17, 2022", "November 17, 2024", ""),
        ("10.2", "February 27, 2022", "August 27, 2025", "March 31, 2027<sup>^</sup>"), ("10.1", "May 31, 2021", "December 1, 2024", ""),
        ("10.0", "July 16, 2020", "July 16, 2022", ""), ("9.1", "December 13, 2019", "June 30, 2024", ""),
        ("9.0", "February 6, 2019", "March 1, 2022", ""), ("8.1", "March 1st, 2018", "March 1, 2022", "")])
    branches = lifecycle.parse_lifecycle(f'<table id="pan-os-panorama"><tr><th>Version</th></tr>{rows}</table>')
    assert branches["10.2"] == {"released": "2022-02-27", "support": "2025-08-27", "extended": "2027-03-31"}
    assert branches["8.1"]["released"] == "2018-03-01" and branches["11.0"]["extended"] is None


def test_new_release_and_added_issues_are_logged():
    known = parser.Page(kind="known", title="", version="11.2.14", issues=[{"ids": ["PAN-2"]}, {"ids": ["PAN-1"]}])
    assert extract.page_changes(known, {"issues": [{"ids": ["PAN-1"]}]}, "2026-11-10") == \
        [{"date": "2026-11-10", "version": "11.2.14", "kind": "known_added", "bugs": ["PAN-2"]}]
    addressed = parser.Page(kind="addressed", title="", version="11.2.14-h1", issues=[{"ids": ["PAN-3"]}])
    assert extract.page_changes(addressed, None, "2026-11-10")[0]["kind"] == "version"
    assert extract.page_changes(known, None, "2026-11-10") == []


def doc(path, kind, version, issues=(), changes=()):
    return {"path": path, "branch": ".".join((version or "11.2.0").split(".")[:2]), "kind": kind, "version": version,
            "issues": list(issues), "changes": list(changes)}


def issue(bug, text="x", resolved=None):
    return {"ids": [bug], "description": text, "workaround": None, "resolved_in": resolved}


def test_build_crosses_pages_into_events():
    documents = [
        doc("a/k12", "known", "11.2.12", [issue("PAN-1", "Problem on PA-5420.", "11.2.13-h1"), issue("PAN-2", "Open.")]),
        doc("a/a12", "addressed", "11.2.12"),
        doc("a/a13h1", "addressed", "11.2.13-h1", [issue("PAN-1", "Fixed an issue.")]),
        doc("a/a13", "addressed", "11.2.13", [issue("PAN-3")]),
        doc("a/lim", "limitations", None, [issue("PAN-4", "Limit.", "11.2.13")]),
        doc("a/chg", "changes", None, changes=[["DoS", "In PAN-OS 11.2.13 and later the default is 30 seconds."], ["IKE", "IKEv2."]]),
    ]
    data = build.build_data(documents, {}, {"source": None, "branches": {}}, [])
    index, rows = data["index"], {row[0]: row for row in data["bugs"]["bugs"]}
    names = [v["v"] for v in index["versions"]]
    assert names == ["11.2.12", "11.2.13", "11.2.13-h1"]
    first = rows["PAN-1"]
    assert first[1] == "Problem on PA-5420." and first[6] == "Fixed an issue." and first[3] == ["PA-5420"]
    assert [(names[e[0]], e[1]) for e in first[5]] == [("11.2.12", "k"), ("11.2.13-h1", "r")]
    # The branch limitation holds up to its fix only.
    assert [(names[e[0]], e[1], e[3]) for e in rows["PAN-4"][5]] == [("11.2.12", "l", 1), ("11.2.13", "r", 0)]
    assert [c[0] for c in index["versions"][1]["changes"]] == ["DoS"]
    assert [c[0] for c in index["versions"][0]["changes"]] == ["IKE"]
    assert index["branches"]["11.2"] == {"limitations": index["pages"].index("a/lim"), "changes": index["pages"].index("a/chg")}


def test_cn_series_pages_cover_a_generation():
    assert collect.branch_of_path("cn-series/release-notes/cn-series-10-x-release-notes/known-issues-in-cn-series-10-x") == "10.x"
    assert collect.branch_of_path("cn-series/release-notes/known-issues-in-cn-series-10-x") is None
    assert collect.branch_of_path("cn-series/release-notes/cn-series-11-x-release-notes/cn-series-11-2-0") is None
    documents = [
        doc("a/a1", "addressed", "10.1.4"), doc("a/a2", "addressed", "10.2.3"), doc("a/a2h", "addressed", "10.2.3-h1"),
        doc("a/b1", "addressed", "11.1.0"),
        {**doc("cn/k10", "known", None, [issue("PAN-207845", "Pods do not come up.")]), "branch": "10.x"},
        {**doc("cn/a10", "addressed", None, [issue("CN-181", "Fixed an issue.")]), "branch": "10.x"},
    ]
    data = build.build_data(documents, {}, {"source": None, "branches": {}}, [])
    index, rows = data["index"], {row[0]: row for row in data["bugs"]["bugs"]}
    names = [v["v"] for v in index["versions"]]
    known = rows["PAN-207845"]
    # Every maintenance release of 10.x, none of 11.x, hotfixes inherit; family CN-Series forced.
    assert [(names[e[0]], e[1], e[3]) for e in known[5]] == [("10.1.4", "k", 1), ("10.2.3", "k", 1)]
    assert index["families"][known[4][0]] == "CN-Series"
    fixed = rows["CN-181"]
    assert fixed[5] == [] and fixed[7] == ["CN-Series 10.x", index["pages"].index("cn/a10")]
    assert index["series"] == {str(index["pages"].index("cn/a10")): "CN-Series 10.x", str(index["pages"].index("cn/k10")): "CN-Series 10.x"}
    assert "10.x" not in index["branches"]


from palobugs.hardware import hardware_index, parse_hardware, product_models


def test_hardware_rows_keep_firewalls_and_appliances():
    assert product_models("PA-7000 Series (PAN-PA-7000-100G-NPC-A, PAN-PA-7080-AC-SYS, PAN-PA-7050-DC-SYS, PAN-PA-7050-SMC-B)") == ["PA-7050", "PA-7080"]
    assert product_models("PA-800 Series (PA-820, PA-850) (PA-820-ZTP, PA-850-ZTP)") == ["PA-820", "PA-850"]
    assert product_models("K2-Series (PA-5280-K2, PA-7050-K2)") == []
    assert product_models("PAN-2.5IN-HDD-2TB-PAIR") == []
    row = "<tr><td>{}</td><td>{}</td><td>{}</td><td></td><td>{}</td><td></td></tr>"
    page = "<table><tr><th>End-of-Sale Product</th></tr>" + "".join([
        row.format("PA-220", "January 31, 2023", "January 31, 2028", "PAN-OS 10.2 Standard Support: Until August 27, 2025"),
        row.format("M-100", "October 31, 2018", "October 31, 2023 (EOL)", "(16GB) PAN-OS 8.1 (EOL) (32GB) PAN-OS 9.1 *"),
        row.format("LightCyber Magna Master (M-100)", "December 31, 2017", "December 31, 2020 (EOL)", "Magna 3.9 (EOL)"),
        row.format("ION 3000", "March 15th, 2024", "August 1st, 2029", "Prisma SD-WAN ION 6.5"),
    ]) + "</table>"
    found = parse_hardware(page)
    assert [(a["models"], a["last_software"], a["end_of_life"]) for a in found] == [
        (["PA-220"], "10.2", "2028-01-31"), (["M-100"], "9.1", "2023-10-31"),
    ]
    index = hardware_index(["PA-460"], {"source": "s", "announcements": found})
    assert list(index["models"]) == ["M-100", "PA-220", "PA-460"]
    assert index["models"]["PA-220"]["eol"] == [[["PA-220"], None, "10.2", "2028-01-31", found[0]["page"]]]
    assert index["models"]["PA-220"]["family"] == "PA-200 Series"
