"use strict";
// What the site concludes from the notes, kept apart from the page so it can be tested.

/** Branch, maintenance release and hotfix number: 11.2.13-h3 is train 11.2.13, maintenance 13, hotfix 3. */
function releaseParts(version) {
  const match = version.match(/^(\d+\.\d+)\.(\d+)(?:-h(\d+))?$/);
  return { branch: match[1], train: `${match[1]}.${match[2]}`, r: Number(match[2]), s: Number(match[3] || 0) };
}

/**
 * Whether a fix in one release is in another of the same branch. A maintenance
 * release carries the fixes of the earlier ones; a hotfix only carries those of
 * its own train: 11.2.13-h3 is in 11.2.13-h4, not in 11.2.12-h9 nor in 11.2.14.
 */
function covers(fix, target) {
  if (fix.branch !== target.branch) return false;
  if (fix.s === 0) return fix.r <= target.r;
  return fix.train === target.train && fix.s <= target.s;
}

/** Status of a bug on one release, from what the notes of its branch say. */
function statusAt(bug, index, versions) {
  const target = versions[index];
  const own = bug.events.filter(([v]) => versions[v].branch === target.branch);
  if (own.some(([v, status]) => v === index && status !== "r")) return { key: "affected" };

  const fixed = own.find(([v, status]) => status === "r" && covers(versions[v], target));
  if (fixed) return { key: "fixed", detail: { id: "fixedSince", version: versions[fixed[0]].v } };

  // A hotfix has no Known Issues page: it carries those of its maintenance release, unless a fix is documented.
  // Only for a hotfix: a release whose Known Issues drop an issue may have fixed it silently.
  const inherited = target.s > 0 && [...own].reverse().find(([v, status]) => status !== "r" && v !== index && covers(versions[v], target));
  if (inherited) return { key: "affected", detail: { id: "openSince", version: versions[inherited[0]].v } };

  const fixedLater = own.find(([v, status]) => status === "r" && v > index);
  if (fixedLater) return { key: "potential", detail: { id: "fixedIn", version: versions[fixedLater[0]].v } };

  const knownLater = own.find(([v]) => v > index);
  if (knownLater) return { key: "potential", detail: { id: "knownIn", version: versions[knownLater[0]].v } };

  if (own.length) {
    const last = own[own.length - 1][0];
    return { key: "unknown", detail: { id: "dropped", version: versions[last].v } };
  }
  return { key: "unknown", detail: { id: "noMention" } };
}

/** The first fix of each train, newest first, as positions in the list of releases. */
function firstFixes(events, versions) {
  const found = new Map();
  for (const [v, status] of events) {
    if (status !== "r") continue;
    const { train } = versions[v];
    if (!found.has(train)) found.set(train, v);
  }
  // A fix in a maintenance release already covers the later releases of its branch.
  const kept = [...found.values()].filter((v) => ![...found.values()].some((other) => other !== v && versions[other].s === 0 && covers(versions[other], versions[v])));
  return kept.sort((a, b) => b - a);
}

function compareBranches(a, b) {
  const [majorA, minorA] = a.split(".").map(Number);
  const [majorB, minorB] = b.split(".").map(Number);
  return majorA - majorB || minorA - minorB;
}

/**
 * Support on a date. "inExtended": past the standard support, within the extended
 * one. A branch missing from the table: older ones ended, newer ones are not dated yet.
 */
function branchSupport(branch, branches, today) {
  const dates = branches[branch];
  if (dates) {
    const supported = today <= dates.support;
    return { ...dates, supported, inExtended: !supported && Boolean(dates.extended) && today <= dates.extended };
  }
  return { supported: Object.keys(branches).every((listed) => compareBranches(branch, listed) > 0), inExtended: false };
}

/** Branches where the notes mention a bug and which are still supported, newest first. */
function supportedBranches(events, versions) {
  const branches = new Set(events.map(([version]) => versions[version]).filter((entry) => entry.support.supported).map((entry) => entry.branch));
  return [...branches].sort(compareBranches).reverse();
}

/**
 * Inclusive filter. The selection is "f:<family>" or "m:<model>"; familyOf gives
 * the position of the family of a model. "cited": the text names the model.
 * "family": the text names its family without naming one of its models.
 * "generic": the text names no hardware at all, so the bug stays listed.
 */
function hardwareMatch(bug, selection, families, familyOf) {
  if (!selection) return "all";
  const kind = selection.slice(0, 1);
  const name = selection.slice(2);
  const family = kind === "f" ? families.indexOf(name) : familyOf(name);
  if (!bug.families.length && !bug.models.length) return "generic";
  if (kind === "f") return bug.families.includes(family) ? "family" : null;
  if (bug.models.includes(name)) return "cited";
  if (bug.models.some((model) => familyOf(model) === family)) return null;
  return bug.families.includes(family) ? "family" : null;
}

function searchTerms(query) {
  return query.toLowerCase().split(/[\s,;]+/).filter(Boolean);
}

/** "PAN-338608", or its number alone. A model as "PA-5420" is a keyword, not an issue. */
function idTerm(term, prefixes) {
  const match = term.match(/^(?:([a-z][a-z0-9]{1,9})-)?(\d{3,7})$/);
  if (!match) return null;
  if (match[1]) return prefixes.has(match[1]) ? { prefix: match[1], number: match[2] } : null;
  return match[2].length >= 5 ? { prefix: null, number: match[2] } : null;
}

function matchesTerms(bug, terms, prefixes) {
  return terms.every((term) => {
    const id = idTerm(term, prefixes);
    if (!id) return bug.text.includes(term);
    const [prefix, number] = bug.id.toLowerCase().split("-");
    return number === id.number && (!id.prefix || prefix === id.prefix);
  });
}

function upgradeGroup(bug, from, to, versions) {
  const before = statusAt(bug, from, versions).key;
  const after = statusAt(bug, to, versions).key;
  if (after === "fixed" && before !== "fixed") return "gained";
  if (after === "affected") return before === "affected" ? "remaining" : "introduced";
  return null;
}

/**
 * Releases crossed by an upgrade: the first release of each later branch up to
 * the target branch, then the releases of the target branch up to the target.
 */
function upgradePath(versions, from, to) {
  if (from >= to) return [];
  const target = versions[to].branch;
  const start = versions[from].branch;
  const firsts = new Map();
  versions.forEach((entry, index) => {
    if (!firsts.has(entry.branch)) firsts.set(entry.branch, index);
  });
  const path = [];
  for (let index = from + 1; index <= to; index += 1) {
    const branch = versions[index].branch;
    if (branch === target || (branch !== start && firsts.get(branch) === index)) path.push(index);
  }
  return path;
}

/** Changes of default behavior met on the way. */
function versionChanges(versions, from, to) {
  const found = new Map();
  for (const index of upgradePath(versions, from, to)) {
    const entry = versions[index];
    for (const [feature, text, page] of entry.changes) {
      const key = `${entry.branch} ${feature} ${text}`;
      if (!found.has(key)) found.set(key, { feature, text, page, entry });
    }
  }
  return [...found.values()];
}

/** Pages of the branches crossed by an upgrade, target branch first: changes of default behavior, limitations. */
function upgradeReading(branchPages, versions, from, to) {
  if (from >= to) return [];
  const crossed = [...new Set(upgradePath(versions, from, to).map((index) => versions[index].branch))].reverse();
  return crossed.flatMap((branch) => ["changes", "limitations"]
    .filter((kind) => branchPages[branch] && branchPages[branch][kind] !== undefined)
    .map((kind) => ({ branch, kind, page: branchPages[branch][kind] })));
}

/** Per model: the bugs whose text names it, and the first and last releases where they appear. */
function modelSummaries(models, bugs, versions) {
  const summaries = new Map(models.map(([model, family]) => [model, { model, family, count: 0, first: Infinity, last: -1 }]));
  for (const bug of bugs) {
    for (const model of bug.models) {
      const summary = summaries.get(model);
      if (!summary) continue;
      summary.count += 1;
      for (const [version] of bug.events) {
        summary.first = Math.min(summary.first, version);
        summary.last = Math.max(summary.last, version);
      }
    }
  }
  return [...summaries.values()].filter((summary) => summary.count && summary.last >= 0).map((summary) => ({
    ...summary, first: versions[summary.first].v, last: versions[summary.last].v,
  }));
}

/** Link to the official page holding a fact. */
function officialUrl(site, pages, page) {
  return page === null || page === undefined ? null : `${site}${pages[page]}`;
}

/** Tab-separated text, which spreadsheets and mail clients paste as a table. */
function tableText(rows) {
  return rows.map((row) => row.map((cell) => String(cell ?? "").replace(/\s+/g, " ").trim()).join("\t")).join("\n");
}

if (typeof module !== "undefined") {
  module.exports = {
    releaseParts, covers, firstFixes, statusAt, branchSupport, supportedBranches, hardwareMatch, searchTerms, idTerm,
    matchesTerms, upgradeGroup, upgradePath, versionChanges, upgradeReading, modelSummaries, officialUrl, tableText,
  };
}
