"use strict";

const PAGE_SIZE = 100;
const PRODUCT = "PAN-OS";
const KNOWN_LABELS = { k: t("known.k"), l: t("known.l"), r: t("status.fixed") };
const STATUSES = {
  affected: t("status.affected"),
  potential: t("status.potential"),
  fixed: t("status.fixed"),
  unknown: t("status.unknown"),
};
const SCOPES = {
  all: { label: t("scope.all"), tone: "all" },
  supported: { label: t("scope.supported"), tone: "fixed" },
  ended: { label: t("scope.ended"), tone: "unknown" },
};
// Riskiest first: what an upgrade brings or leaves matters more than what it fixes.
const UPGRADE_GROUPS = {
  all: { label: t("group.all"), tone: "all" },
  changed: { label: t("group.changed"), tone: "change" },
  introduced: { label: t("group.introduced"), tone: "affected" },
  remaining: { label: t("group.remaining"), tone: "potential" },
  gained: { label: t("group.gained"), tone: "fixed" },
};

const $ = (id) => document.getElementById(id);
const defaultFilters = () => ({
  query: "", version: "", from: "", model: "",
  hidden: new Set(["unknown"]), group: "all", scope: "all",
});
const state = { view: "bugs", shown: PAGE_SIZE, reading: false, ...defaultFilters() };
let versions = [];
let families = [];
let models = [];
let modelFamilies = new Map();
let bugs = [];
let changes = [];
let summaries = [];
let lifecycle = { source: null, branches: {} };
let site = "";
let pages = [];
let branchPages = {};
let seriesPages = {};
let prefixes = new Set();
let copiedTable = () => [];
let updated = "";
let schedule = null;
let searchTimer;
const combos = {};

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const formatNumber = (n) => n.toLocaleString(locale);
const formatDate = (iso) => iso.split("-").reverse().join("/");
const familyOf = (model) => (modelFamilies.has(model) ? modelFamilies.get(model) : -1);

/** Text field that filters a list of options as you type. */
class Combobox {
  constructor(root, onChange) {
    this.onChange = onChange;
    this.options = [];
    this.current = "";
    this.visible = [];
    this.active = -1;
    this.input = document.createElement("input");
    this.input.id = `${root.id}-input`;
    this.input.type = "text";
    this.input.autocomplete = "off";
    this.input.spellcheck = false;
    this.input.setAttribute("role", "combobox");
    this.input.setAttribute("aria-autocomplete", "list");
    this.input.setAttribute("aria-expanded", "false");
    this.input.setAttribute("aria-controls", `${root.id}-list`);
    this.list = document.createElement("ul");
    this.list.id = `${root.id}-list`;
    this.list.className = "combo-list";
    this.list.setAttribute("role", "listbox");
    this.list.hidden = true;
    root.append(this.input, this.list);

    this.input.addEventListener("focus", () => { this.open(""); this.input.select(); });
    this.input.addEventListener("click", () => {
      if (this.list.hidden) this.open("");
      // Deferred: a click on selected text collapses the selection after this event.
      setTimeout(() => {
        if (this.input.value === this.label()) this.input.select();
      });
    });
    this.input.addEventListener("input", () => this.open(this.input.value));
    this.input.addEventListener("blur", () => this.close());
    this.input.addEventListener("keydown", (event) => this.onKey(event));
    // mousedown, not click: the field must not lose focus before the choice is made.
    this.list.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const option = event.target.closest("[data-index]");
      if (option) this.choose(this.visible[Number(option.dataset.index)]);
    });
  }

  setOptions(options) {
    this.options = options;
    this.value = this.current;
  }

  get value() {
    return this.current;
  }

  set value(value) {
    this.current = value;
    this.input.value = this.label();
  }

  label() {
    const option = this.options.find((entry) => entry.value === this.current);
    return option ? option.label : "";
  }

  open(text) {
    const terms = text.toLowerCase().split(/\s+/).filter(Boolean);
    this.visible = this.options.filter((option) => {
      const label = `${option.label} ${option.group || ""}`.toLowerCase();
      return terms.every((term) => label.includes(term));
    });
    const selected = this.visible.findIndex((option) => option.value === this.current);
    this.active = terms.length ? 0 : Math.max(selected, 0);
    this.renderList();
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    this.scrollToActive();
  }

  close() {
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.value = this.current;
    // Still focused after Escape or a choice: typing must replace the label.
    if (document.activeElement === this.input) this.input.select();
  }

  choose(option) {
    const changed = option.value !== this.current;
    this.current = option.value;
    this.close();
    if (changed) this.onChange(option.value);
  }

  onKey(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.list.hidden) {
        this.open("");
      } else if (this.visible.length) {
        const step = event.key === "ArrowDown" ? 1 : -1;
        this.active = (this.active + step + this.visible.length) % this.visible.length;
        this.renderList();
        this.scrollToActive();
      }
    } else if (event.key === "Enter" && !this.list.hidden) {
      event.preventDefault();
      if (this.visible[this.active]) this.choose(this.visible[this.active]);
    } else if (event.key === "Escape") {
      this.close();
    }
  }

  renderList() {
    let group = null;
    const items = [];
    this.visible.forEach((option, index) => {
      const tone = option.tone ? ` ${option.tone}` : "";
      if (option.group && option.group !== group) {
        group = option.group;
        items.push(`<li class="combo-group${tone}" role="presentation">${escapeHtml(group)}</li>`);
      }
      const classes = `combo-option${tone}${index === this.active ? " active" : ""}`;
      items.push(`<li id="${this.list.id}-${index}" class="${classes}" role="option" data-index="${index}" aria-selected="${option.value === this.current}">${escapeHtml(option.label)}</li>`);
    });
    this.list.innerHTML = items.join("") || `<li class="combo-empty">${t("filter.noResult")}</li>`;
  }

  scrollToActive() {
    const option = this.list.querySelector(".active");
    if (!option) return;
    option.scrollIntoView({ block: "nearest" });
    this.input.setAttribute("aria-activedescendant", option.id);
  }
}

function hydrate(row) {
  const [id, description, workaround, cited, familyList, events, fix, seriesFix] = row;
  const fixes = firstFixes(events, versions);
  const text = `${id} ${description} ${workaround || ""} ${fix || ""} ${cited.join(" ")}`.toLowerCase();
  const supported = supportedBranches(events, versions);
  return { id, description, workaround, models: cited, families: familyList, events, fixes, text, supported, fix, seriesFix };
}

/** The branch filter only makes sense on a search across all the releases. */
function scopeApplies() {
  return state.view === "bugs" && !state.version && Object.keys(lifecycle.branches).length > 0;
}

function versionIndex(value) {
  return value === "" ? -1 : versions.findIndex((entry) => entry.v === value);
}

function compute() {
  const terms = searchTerms(state.query);
  const version = versionIndex(state.version);
  const from = versionIndex(state.from);
  const upgrade = state.view === "upgrade" && version >= 0 && from >= 0;
  const scoped = scopeApplies();
  const counts = {};
  const rows = [];

  if (state.view === "upgrade" && !upgrade) return { rows, counts };
  if (upgrade) {
    for (const change of versionChanges(versions, from, version)) {
      const text = `${change.feature} ${change.text}`.toLowerCase();
      if (!terms.every((term) => text.includes(term))) continue;
      counts.changed = (counts.changed || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.group === "all" || state.group === "changed") rows.push({ change, group: "changed" });
    }
  }
  for (const bug of bugs) {
    if (!matchesTerms(bug, terms, prefixes)) continue;
    const hardware = hardwareMatch(bug, state.model, families, familyOf);
    if (!hardware) continue;

    if (scoped) {
      const scope = bug.supported.length ? "supported" : "ended";
      counts[scope] = (counts[scope] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.scope !== "all" && scope !== state.scope) continue;
    }
    const status = version >= 0 ? statusAt(bug, version, versions) : null;
    if (upgrade) {
      const group = upgradeGroup(bug, from, version, versions);
      if (!group) continue;
      counts[group] = (counts[group] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.group !== "all" && group !== state.group) continue;
      rows.push({ bug, status, hardware, group });
      continue;
    } else if (status) {
      counts[status.key] = (counts[status.key] || 0) + 1;
      if (state.hidden.has(status.key)) continue;
    }
    rows.push({ bug, status, hardware });
  }
  const risk = Object.keys(UPGRADE_GROUPS);
  const cited = (row) => (row.hardware === "cited" ? 0 : 1);
  const ended = (row) => (scoped && !row.bug.supported.length ? 1 : 0);
  rows.sort((a, b) => risk.indexOf(a.group) - risk.indexOf(b.group)
    || (a.change || b.change ? 0 : (state.model ? cited(a) - cited(b) : 0) || ended(a) - ended(b)));
  return { rows, counts };
}

function officialLink(page, label) {
  const url = officialUrl(site, pages, page);
  return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${label}</a>` : label;
}

function highlight(text, terms) {
  const words = terms.filter((term) => !idTerm(term, prefixes)).map(escapeRegExp);
  const safe = escapeHtml(text);
  if (!words.length) return safe;
  return safe.replace(new RegExp(`(${words.map((w) => escapeHtml(w)).join("|")})`, "gi"), "<mark>$1</mark>");
}

function fixesLabel(bug) {
  const labels = bug.fixes.map((version) => versions[version].v);
  // CN-Series names no release for its fixes.
  if (bug.seriesFix) labels.push(t("bug.seriesFix", { series: bug.seriesFix[0] }));
  return labels.length ? t("bug.fixedIn", { versions: labels.join(", ") }) : t("bug.noFix");
}

function hardwareTags(bug, hardware) {
  const tags = bug.models.map((name) => `<span class="tag hw">${escapeHtml(name)}</span>`);
  tags.push(...bug.families.map((position) => `<span class="tag">${escapeHtml(families[position])}</span>`));
  if (hardware === "family") tags.push(`<span class="tag">${t("bug.familyOnly")}</span>`);
  if (hardware === "generic") tags.push(`<span class="tag">${t("bug.generic")}</span>`);
  return tags.join("");
}

/** First mention per branch: Palo Alto Networks does not publish the release that introduced a bug. */
function renderAppearance(bug) {
  const first = new Map();
  for (const [version, status, page, scope] of bug.events) {
    const branch = versions[version].branch;
    if (status !== "r" && !first.has(branch)) first.set(branch, [version, status, scope, page]);
  }
  if (!first.size) return `<p>${t("bug.neverKnown")}</p>`;
  const lines = [...first].reverse().map(([branch, [version, status, scope, page]]) => {
    const key = scope ? (status === "l" ? "bug.branchLimitation" : "bug.branchKnown") : (status === "l" ? "bug.firstLimitation" : "bug.firstKnown");
    return `<dt>${escapeHtml(branch)}</dt><dd>${escapeHtml(t(key, { version: versions[version].v, branch: pageName(page, branch) }))}</dd>`;
  });
  return `<dl class="history">${lines.join("")}</dl><p class="note">${t("bug.appearanceNote")}</p>`;
}

/** One line per fact, newest first; a page of a whole branch gives one line, not one per release. */
function renderHistory(bug) {
  const lines = [];
  const seen = new Set();
  for (const [version, status, page, scope] of [...bug.events].reverse()) {
    const entry = versions[version];
    if (scope) {
      const key = `${entry.branch} ${status} ${page}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const span = bug.events.filter(([v, s, p, sc]) => sc && s === status && p === page).map(([v]) => versions[v].v);
      const range = span.length > 1 ? `${span[0]} → ${span[span.length - 1]}` : span[0];
      lines.push(`<dt>${escapeHtml(range)}</dt><dd>${KNOWN_LABELS[status]}, ${officialLink(page, t(status === "l" ? "bug.limitationsPage" : "bug.knownPage", { branch: pageName(page, entry.branch) }))}</dd>`);
      continue;
    }
    const label = status === "r" ? t("bug.addressedPage", { version: entry.v }) : t("bug.knownPage", { branch: entry.v });
    lines.push(`<dt>${escapeHtml(entry.v)}</dt><dd>${KNOWN_LABELS[status]}, ${officialLink(page, label)}</dd>`);
  }
  if (bug.seriesFix) {
    const [series, page] = bug.seriesFix;
    lines.push(`<dt>${escapeHtml(series)}</dt><dd>${KNOWN_LABELS.r}, ${officialLink(page, t("bug.addressedPage", { version: series }))}</dd>`);
  }
  return `<dl class="history">${lines.join("")}</dl>`;
}

/** "CN-Series 10.x" for a page of the CN-Series notes, else the branch. */
function pageName(page, branch) {
  return seriesPages[page] || branch;
}

function statusDetail(detail) {
  return detail ? `<span>${escapeHtml(t(`detail.${detail.id}`, detail))}</span>` : "";
}

function supportTag(bug) {
  if (!scopeApplies()) return "";
  return bug.supported.length
    ? `<span class="tag supported">${t("bug.supported", { branches: escapeHtml(bug.supported.join(", ")) })}</span>`
    : `<span class="tag">${t("scope.ended")}</span>`;
}

function renderChange({ feature, text, page, entry }, terms) {
  const link = officialLink(page, t("change.page", { branch: escapeHtml(entry.branch) }));
  return `<div class="bug"><div class="bug-row">
    <span class="bug-id">${escapeHtml(entry.v)}</span>
    <span class="bug-text"><strong>${highlight(feature, terms)}</strong> ${highlight(text, terms)}</span>
    <span class="bug-meta"><span class="badge change">${t("change.label")}</span>${link}</span>
  </div></div>`;
}

function renderBug({ bug, status, hardware, group, change }, terms) {
  if (change) return renderChange(change, terms);
  const badge = group
    ? `<span class="badge ${UPGRADE_GROUPS[group].tone}">${UPGRADE_GROUPS[group].label}</span>`
    : status
      ? `<span class="badge ${status.key}">${STATUSES[status.key]}</span>${statusDetail(status.detail)}`
      : "";
  const workaround = bug.workaround
    ? `<h3>${t("bug.workaround")}</h3><p>${highlight(bug.workaround, terms)}</p>`
    : "";
  const fix = bug.fix ? `<h3>${t("bug.fix")}</h3><p>${highlight(bug.fix, terms)}</p>` : "";
  const description = bug.description ? highlight(bug.description, terms) : `<em>${t("bug.noDescription")}</em>`;
  return `<details class="bug" data-id="${escapeHtml(bug.id)}">
    <summary>
      <span class="bug-id">${escapeHtml(bug.id)}</span>
      <span class="bug-text">${description}</span>
      <span class="bug-meta">${badge}<span>${escapeHtml(fixesLabel(bug))}</span>${supportTag(bug)}${hardwareTags(bug, hardware)}</span>
    </summary>
    <div class="bug-detail">${fix}<h3>${t("bug.appearance")}</h3>${renderAppearance(bug)}${workaround}<h3>${t("bug.history")}</h3>${renderHistory(bug)}</div>
  </details>`;
}

function tile(data, key, label, tone, count, pressed) {
  return `<button type="button" class="summary-card ${tone}" data-${data}="${key}" aria-pressed="${pressed}"><strong>${formatNumber(count || 0)}</strong><span>${label}</span></button>`;
}

function renderChips(counts) {
  const version = versionIndex(state.version);
  if (state.view === "upgrade") {
    const compared = version >= 0 && versionIndex(state.from) >= 0;
    $("chips").innerHTML = compared
      ? Object.entries(UPGRADE_GROUPS)
        // The order of the tiles helps finding one; the list keeps the riskiest first.
        .sort(([a, { label: first }], [b, { label: second }]) => (b === "all") - (a === "all") || first.localeCompare(second, locale))
        .map(([key, { label, tone }]) => tile("group", key, label, tone, counts[key], state.group === key)).join("")
      : "";
  } else if (scopeApplies()) {
    $("chips").innerHTML = Object.entries(SCOPES).map(([key, { label, tone }]) => tile("scope", key, label, tone, counts[key], state.scope === key)).join("");
  } else if (version >= 0) {
    $("chips").innerHTML = Object.entries(STATUSES).map(([key, label]) => tile("status", key, label, key, counts[key], !state.hidden.has(key))).join("");
  } else {
    $("chips").innerHTML = "";
  }
}

function renderNotices() {
  const messages = [];
  const version = versionIndex(state.version);
  const from = versionIndex(state.from);
  for (const index of [version, state.view === "upgrade" ? from : -1]) {
    const entry = index >= 0 ? versions[index] : null;
    if (entry && !entry.hotfix && entry.known === null) messages.push(t("notice.noKnown", { version: entry.v }));
  }
  if (state.view === "upgrade" && from >= 0 && version >= 0 && from >= version) {
    messages.push(t("notice.order"));
  }
  const crossed = state.view === "upgrade" && from >= 0 && version > from
    ? upgradePath(versions, from, version).filter((index) => versions[index].changes.length) : [];
  if (crossed.length) messages.push(t("notice.path", { path: crossed.map((index) => versions[index].v).join(", ") }));
  $("notices").innerHTML = messages.map((text) => `<p class="notice">${escapeHtml(text)}</p>`).join("");
}

function supportBadge(support) {
  if (!Object.keys(lifecycle.branches).length) return "";
  if (!support.support && support.supported) return "";
  const date = support.support && formatDate(support.support);
  const [tone, text] = !support.support ? ["unknown", t("support.ended")]
    : support.supported ? ["fixed", t("support.until", { date })]
      : support.inExtended ? ["potential", t("support.extendedUntil", { date: formatDate(support.extended) })]
        : ["unknown", t("support.endedOn", { date })];
  return `<a class="badge ${tone}" href="${escapeHtml(lifecycle.source)}" target="_blank" rel="noopener">${text}</a>`;
}

/** Shortcuts to the latest release of each supported branch. */
function renderSupport() {
  const latest = new Map(versions.map((entry) => [entry.branch, entry]));
  const branches = [...latest.values()].filter((entry) => entry.support.supported).reverse();
  const shown = ["bugs", "upgrade"].includes(state.view) && Object.keys(lifecycle.branches).length > 0;
  $("support").hidden = !shown;
  if (!shown) return;
  const links = branches.map((entry) => {
    const params = stateParams();
    params.set("version", entry.v);
    const date = entry.support.support ? `<small>${t("support.date", { date: formatDate(entry.support.support) })}</small>` : "";
    const current = entry.v === state.version ? ' aria-current="true"' : "";
    return `<a class="support-branch" href="#${escapeHtml(params.toString())}"${current}><strong>${escapeHtml(entry.v)}</strong>${date}</a>`;
  });
  const note = t("support.note", { url: escapeHtml(lifecycle.source) });
  $("support").innerHTML = `<h2>${t("support.title")}</h2><div class="support-list">${links.join("")}</div><p class="muted">${note}</p>`;
}

function renderVersionInfo() {
  const entry = versions[versionIndex(state.version)];
  const parts = [];
  if (entry) {
    parts.push(`${PRODUCT} ${escapeHtml(entry.v)}${entry.hotfix ? ` · ${t("version.hotfix")}` : ""}`);
    if (entry.released) parts.push(t("version.detected", { date: formatDate(entry.released) }));
    if (entry.revised) parts.push(t("version.revised", { date: formatDate(entry.revised) }));
    const support = supportBadge(entry.support);
    if (support) parts.push(support);
    if (entry.addressed !== null) parts.push(officialLink(entry.addressed, t("version.addressed")));
    const known = entry.known !== null ? entry.known : versions.find((other) => other.v === entry.train)?.known;
    if (known !== null && known !== undefined) parts.push(officialLink(known, t("version.known", { version: entry.train })));
  }
  $("version-info").innerHTML = parts.map((part) => `<span>${part}</span>`).join("");
}

function renderUpgradeNotices() {
  const from = versionIndex(state.from);
  const to = versionIndex(state.version);
  const items = state.view === "upgrade" && from >= 0 && to > from ? upgradeReading(branchPages, versions, from, to) : [];
  if (!items.length) {
    $("upgrade-notices").innerHTML = "";
    return;
  }
  const columns = ["changes", "limitations"].map((kind) => {
    const list = items.filter((item) => item.kind === kind)
      .map((item) => `<li>${officialLink(item.page, escapeHtml(t(`reading.${kind}Page`, { branch: item.branch })))}</li>`).join("");
    return list ? `<section><h3>${t(`reading.${kind}`)}</h3><ul>${list}</ul></section>` : "";
  }).join("");
  $("upgrade-notices").innerHTML = `<details class="reading"${state.reading ? " open" : ""}><summary>${t("reading.title")}</summary>
    <p class="muted">${t("reading.help")}</p><div class="reading-chapters">${columns}</div></details>`;
}

/** Releases holding the most recent value of a date field, newest release first. */
function latestBy(field) {
  const dated = versions.filter((entry) => entry[field]);
  const date = dated.reduce((latest, entry) => (entry[field] > latest ? entry[field] : latest), "");
  return { date, entries: dated.filter((entry) => entry[field] === date).reverse() };
}

function newsCard(title, date, entries) {
  const links = entries.slice(0, 8).map((entry) => `<a href="#${escapeHtml(new URLSearchParams({ version: entry.v }).toString())}">${escapeHtml(entry.v)}</a>`);
  const more = entries.length > links.length ? ` ${t("news.more", { count: formatNumber(entries.length - links.length) })}` : "";
  return `<section class="news-card"><h2>${title}</h2><strong>${date}</strong><p>${PRODUCT} ${links.join(", ")}${more}</p></section>`;
}

function latestCard(title, field) {
  const { date, entries } = latestBy(field);
  return date ? newsCard(title, formatDate(date), entries) : "";
}

function pageLine(version) {
  const entry = versions.find((candidate) => candidate.v === version);
  if (!entry || !entry.revised) return "";
  return `<p class="news-pdf version-info"><span>${t("news.revised", { date: formatDate(entry.revised) })}</span> ${officialLink(entry.addressed, t("version.addressed"))}</p>`;
}

function bugTable(rows) {
  const header = ["copy.bug", "copy.status", "copy.description", "copy.workaround", "copy.fix"].map((key) => t(key));
  return [header, ...rows.map(({ bug, status, group, change }) => (change ? [
    change.entry.v, UPGRADE_GROUPS[group].label, `${change.feature} : ${change.text}`, "", "",
  ] : [
    bug.id,
    group ? UPGRADE_GROUPS[group].label : status ? STATUSES[status.key] : "",
    bug.description,
    bug.workaround,
    fixesLabel(bug),
  ]))];
}

/** The Clipboard API needs HTTPS: a local preview over HTTP falls back on the old command. */
async function copyText(text) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  document.body.append(field);
  field.select();
  document.execCommand("copy");
  field.remove();
}

function clearPanels() {
  $("notices").innerHTML = "";
  $("version-info").innerHTML = "";
  $("upgrade-notices").innerHTML = "";
  $("more").hidden = true;
}

function renderHardware() {
  const terms = searchTerms($("hardware-query").value);
  const listed = summaries
    .map((entry) => ({ ...entry, familyName: families[entry.family] }))
    .filter(({ model, familyName }) => terms.every((term) => `${model} ${familyName}`.toLowerCase().includes(term)))
    .sort((a, b) => a.model.localeCompare(b.model, "fr", { numeric: true }));
  const columns = ["model", "family", "count", "first", "last"];
  copiedTable = () => [columns.map((key) => t(`hardware.${key}`)), ...listed.map((entry) => [entry.model, entry.familyName, entry.count, entry.first, entry.last])];
  $("copy").hidden = !listed.length;
  $("copy").textContent = t("list.copy");
  $("chips").innerHTML = "";
  const rows = listed.map((entry) => {
    const filter = new URLSearchParams({ model: `m:${entry.model}` });
    const family = new URLSearchParams({ model: `f:${entry.familyName}` });
    return `<tr><th scope="row"><a href="#${escapeHtml(filter.toString())}">${escapeHtml(entry.model)}</a></th>
      <td><a href="#${escapeHtml(family.toString())}">${escapeHtml(entry.familyName)}</a></td><td>${formatNumber(entry.count)}</td>
      <td>${escapeHtml(entry.first)}</td><td>${escapeHtml(entry.last)}</td></tr>`;
  });
  $("results").innerHTML = rows.length
    ? `<table class="hardware-table"><thead><tr>${columns.map((key) => `<th scope="col">${t(`hardware.${key}`)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`
    : "";
  $("count").textContent = rows.length ? t("hardware.listed", { count: formatNumber(rows.length) }) : t("hardware.none");
  clearPanels();
  $("news-summary").innerHTML = "";
  writeHash();
}

function renderNews() {
  $("news-summary").innerHTML = latestCard(t("news.latestRelease"), "released") + latestCard(t("news.latestPage"), "revised");
  const byId = new Map(bugs.map((bug) => [bug.id, bug]));
  const entries = changes.map((change) => {
    const items = change.bugs.slice(0, 20).map((id) => {
      const bug = byId.get(id);
      const link = new URLSearchParams({ query: id });
      return `<li><a href="#${escapeHtml(link.toString())}">${escapeHtml(id)}</a> ${bug ? escapeHtml(bug.description) : ""}</li>`;
    });
    const hidden = change.bugs.length - items.length;
    if (hidden > 0) items.push(`<li class="muted">${t("news.more", { count: formatNumber(hidden) })}</li>`);
    const link = new URLSearchParams({ version: change.version });
    return `<article class="news">
      <time datetime="${change.date}">${formatDate(change.date)}</time>
      <h2><a href="#${escapeHtml(link.toString())}">${escapeHtml(change.titles[language])}</a></h2>
      ${pageLine(change.version)}
      ${items.length ? `<ul>${items.join("")}</ul>` : ""}
    </article>`;
  });
  $("results").innerHTML = entries.join("");
  $("count").textContent = entries.length ? "" : t("news.empty");
  $("copy").hidden = true;
  $("chips").innerHTML = "";
  clearPanels();
  writeHash();
}

function render() {
  renderSupport();
  if (state.view === "news") {
    renderNews();
    return;
  }
  if (state.view === "hardware") {
    renderHardware();
    return;
  }
  $("news-summary").innerHTML = "";
  const { rows, counts } = compute();
  const terms = searchTerms(state.query);
  renderChips(counts);
  renderNotices();
  renderVersionInfo();
  renderUpgradeNotices();

  const waiting = state.view === "upgrade" && (!state.from || !state.version);
  $("count").textContent = waiting
    ? t("count.choose")
    : rows.length > state.shown ? t("count.partial", { count: formatNumber(rows.length), shown: formatNumber(state.shown) })
      : rows.length > 1 ? t("count.many", { count: formatNumber(rows.length) }) : t(rows.length ? "count.one" : "count.none");
  $("results").innerHTML = rows.slice(0, state.shown).map((row) => renderBug(row, terms)).join("");
  $("more").hidden = rows.length <= state.shown;
  $("more").textContent = t("list.more", { count: formatNumber(rows.length - state.shown) });
  copiedTable = () => bugTable(rows);
  $("copy").hidden = !rows.length;
  $("copy").textContent = t("list.copy");
  writeHash();
}

function stateParams(shown = language) {
  const params = new URLSearchParams();
  if (shown === "en") params.set("lang", "en");
  if (state.view !== "bugs") params.set("view", state.view);
  for (const key of ["query", "version", "from", "model"]) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.scope !== "all") params.set("scope", state.scope);
  return params;
}

function writeHash() {
  history.replaceState(null, "", `#${stateParams()}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  state.view = ["upgrade", "news", "hardware"].includes(params.get("view")) ? params.get("view") : "bugs";
  for (const key of ["query", "version", "from", "model"]) {
    state[key] = params.get(key) || "";
  }
  state.scope = ["supported", "ended"].includes(params.get("scope")) ? params.get("scope") : "all";
}

function syncControls() {
  const upgrade = state.view === "upgrade";
  const news = state.view === "news";
  const hardware = state.view === "hardware";
  $("tab-bugs").setAttribute("aria-pressed", String(state.view === "bugs"));
  $("tab-upgrade").setAttribute("aria-pressed", String(upgrade));
  $("tab-news").setAttribute("aria-pressed", String(news));
  $("tab-hardware").setAttribute("aria-pressed", String(hardware));
  $("filters").hidden = news || hardware;
  $("legend").hidden = news || hardware;
  $("hardware-tools").hidden = !hardware;
  $("subscribe").hidden = !news;
  $("field-from").hidden = !upgrade;
  $("version-label").textContent = t(upgrade ? "filter.target" : "filter.version", { system: PRODUCT });
  $("view-help").textContent = t(`help.${state.view}`, { system: PRODUCT });
  for (const key of ["version", "from", "model"]) combos[key].value = state[key];
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme").textContent = t(theme === "dark" ? "theme.light" : "theme.dark");
}

function branchLabel({ branch, support }) {
  if (!Object.keys(lifecycle.branches).length) return `${PRODUCT} ${branch}`;
  if (support.inExtended) return t("option.branchExtended", { system: PRODUCT, branch, date: formatDate(support.extended) });
  if (!support.supported) return t("option.branchEnded", { system: PRODUCT, branch });
  return support.support ? t("option.branchUntil", { system: PRODUCT, branch, date: formatDate(support.support) }) : `${PRODUCT} ${branch}`;
}

function versionOptions(placeholder) {
  const options = [...versions].reverse().map((entry) => ({
    value: entry.v,
    label: entry.v,
    group: branchLabel(entry),
    tone: entry.support.supported ? "" : "ended",
  }));
  return [{ value: "", label: placeholder }, ...options];
}

/** A family first, for its bugs without model, then the models its bugs name. */
function modelOptions() {
  const options = families.flatMap((family, position) => [
    { value: `f:${family}`, label: t("option.family", { family }), group: family },
    ...models.filter(([, familyPosition]) => familyPosition === position)
      .map(([model]) => ({ value: `m:${model}`, label: model, group: family })),
  ]);
  return [{ value: "", label: t("filter.allModels") }, ...options];
}

function update(next) {
  clearTimeout(searchTimer);
  // The field is the reference: a filter can change while a search is debounced.
  Object.assign(state, { query: $("query").value }, next, { shown: PAGE_SIZE });
  syncControls();
  render();
}

function bindEvents() {
  $("query").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => update({}), 150);
  });
  $("theme").addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", theme);
    applyTheme(theme);
  });
  $("reset").addEventListener("click", () => {
    $("query").value = "";
    update(defaultFilters());
  });
  $("language").addEventListener("click", () => {
    const next = language === "fr" ? "en" : "fr";
    localStorage.setItem("language", next);
    history.replaceState(null, "", `#${stateParams(next)}`);
    location.reload();
  });
  $("tab-bugs").addEventListener("click", () => update({ view: "bugs" }));
  $("tab-upgrade").addEventListener("click", () => update({ view: "upgrade" }));
  $("tab-news").addEventListener("click", () => update({ view: "news" }));
  $("tab-hardware").addEventListener("click", () => update({ view: "hardware" }));
  $("hardware-query").addEventListener("input", () => render());
  $("more").addEventListener("click", () => {
    state.shown = Infinity;
    render();
  });
  $("chips").addEventListener("click", (event) => {
    const chip = event.target.closest("button");
    if (!chip) return;
    if (chip.dataset.scope) {
      update({ scope: chip.dataset.scope });
    } else if (chip.dataset.group) {
      update({ group: chip.dataset.group });
    } else {
      const key = chip.dataset.status;
      if (state.hidden.has(key)) state.hidden.delete(key); else state.hidden.add(key);
      update({});
    }
  });
  // toggle does not bubble, and a new render must not fold what the reader opened.
  $("upgrade-notices").addEventListener("toggle", (event) => {
    if (event.target.classList.contains("reading")) state.reading = event.target.open;
  }, true);
  $("copy").addEventListener("click", async () => {
    const table = copiedTable();
    await copyText(tableText(table));
    $("copy").textContent = t("list.copied", { count: formatNumber(table.length - 1) });
  });
  $("to-top").addEventListener("click", () => window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
  window.addEventListener("scroll", () => {
    $("to-top").hidden = window.scrollY < 500;
  }, { passive: true });
  // Selecting text in a bug must not fold or unfold it.
  $("results").addEventListener("click", (event) => {
    if (event.target.closest("summary") && !getSelection().isCollapsed) event.preventDefault();
  });
  window.addEventListener("hashchange", () => {
    readHash();
    $("query").value = state.query;
    update({});
  });
}

async function start() {
  const [index, data, news] = await Promise.all(
    ["index.json", "bugs.json", "changes.json"].map((name) => fetch(`data/${name}`).then((response) => {
      if (!response.ok) throw new Error(`${name}: ${response.status}`);
      return response.json();
    })),
  );
  lifecycle = index.lifecycle;
  const today = new Date().toISOString().slice(0, 10);
  versions = index.versions.map((entry) => ({
    ...entry, ...releaseParts(entry.v), support: branchSupport(entry.branch, lifecycle.branches, today),
  }));
  site = index.site;
  pages = index.pages;
  branchPages = index.branches;
  seriesPages = index.series;
  families = index.families;
  models = index.models;
  modelFamilies = new Map(models);
  changes = news;
  updated = index.updated;
  schedule = index.schedule;
  bugs = data.bugs.map(hydrate);
  prefixes = new Set(bugs.map((bug) => bug.id.toLowerCase().split("-")[0]));
  summaries = modelSummaries(models, bugs, versions);

  for (const key of ["version", "from", "model"]) {
    combos[key] = new Combobox($(key), (value) => update({ [key]: value }));
  }
  combos.version.setOptions(versionOptions(t("filter.allVersions")));
  combos.from.setOptions(versionOptions(t("filter.choose")));
  combos.model.setOptions(modelOptions());

  const latest = versions[versions.length - 1];
  $("scope").textContent = t("page.scopeRange", { system: PRODUCT, first: versions[0].v, last: latest.v });
  $("stats").textContent = t("page.stats", { bugs: formatNumber(bugs.length), versions: formatNumber(versions.length), latest: latest.v });
  const moment = new Date(updated);
  $("updated").textContent = t("page.updated", {
    date: moment.toLocaleDateString(locale),
    time: moment.toLocaleTimeString(locale, { timeStyle: "short" }),
  });
  if (schedule) $("schedule").textContent = t("page.schedule", { crons: schedule.crons.join(t("page.and")), zone: schedule.timezone });
  readHash();
  $("query").value = state.query;
  bindEvents();
  update({});
}

applyTheme(document.documentElement.dataset.theme);
start().catch((error) => {
  $("stats").textContent = t("page.failed");
  console.error(error);
});
