"use strict";
const test = require("node:test");
const assert = require("node:assert");
const logic = require("../../site/logic.js");

const names = ["11.1.4", "11.2.12", "11.2.13", "11.2.13-h1", "11.2.13-h3", "11.2.14", "12.1.2"];
const versions = names.map((v) => ({ v, ...logic.releaseParts(v), changes: [], support: { supported: true } }));
const at = (name) => names.indexOf(name);
const families = ["PA-400 Series", "PA-5400 Series", "VM-Series"];
const familyOf = (model) => ({ "PA-440": 0, "PA-5420": 1, "PA-5410": 1 })[model] ?? -1;

test("a release reads as branch, train, maintenance and hotfix", () => {
  assert.deepStrictEqual(logic.releaseParts("11.2.13-h3"), { branch: "11.2", train: "11.2.13", r: 13, s: 3 });
  assert.deepStrictEqual(logic.releaseParts("12.1.2"), { branch: "12.1", train: "12.1.2", r: 2, s: 0 });
});

test("a hotfix fix covers its own train only", () => {
  const hotfix = logic.releaseParts("11.2.13-h1");
  assert.ok(logic.covers(hotfix, logic.releaseParts("11.2.13-h3")));
  assert.ok(!logic.covers(hotfix, logic.releaseParts("11.2.14")));
  assert.ok(!logic.covers(hotfix, logic.releaseParts("11.2.12")));
  assert.ok(logic.covers(logic.releaseParts("11.2.13"), logic.releaseParts("11.2.14")));
  assert.ok(!logic.covers(logic.releaseParts("11.2.13"), logic.releaseParts("12.1.2")));
});

test("status follows the notes of the branch", () => {
  const bug = { events: [[at("11.2.12"), "k"], [at("11.2.13-h1"), "r"], [at("11.2.14"), "r"]] };
  assert.strictEqual(logic.statusAt(bug, at("11.2.12"), versions).key, "affected");
  assert.strictEqual(logic.statusAt(bug, at("11.2.13-h3"), versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, at("11.2.13"), versions).key, "potential");
  assert.strictEqual(logic.statusAt(bug, at("11.2.14"), versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, at("12.1.2"), versions).key, "unknown");
  assert.strictEqual(logic.statusAt(bug, at("11.1.4"), versions).detail.id, "noMention");
});

test("a hotfix carries the known issues of its release", () => {
  const bug = { events: [[at("11.2.13"), "k"]] };
  const status = logic.statusAt(bug, at("11.2.13-h3"), versions);
  assert.strictEqual(status.key, "affected");
  assert.strictEqual(status.detail.id, "openSince");
  assert.strictEqual(logic.statusAt(bug, at("11.2.14"), versions).key, "unknown");
});

test("the first fix of each train is listed once", () => {
  const events = [[at("11.2.13-h1"), "r"], [at("11.2.13-h3"), "r"], [at("11.2.14"), "r"], [at("12.1.2"), "r"]];
  assert.deepStrictEqual(logic.firstFixes(events, versions).map((i) => names[i]), ["12.1.2", "11.2.14", "11.2.13-h1"]);
  const early = [[at("11.2.12"), "r"], [at("11.2.13-h1"), "r"]];
  assert.deepStrictEqual(logic.firstFixes(early, versions).map((i) => names[i]), ["11.2.12"]);
});

test("hardware filter keeps the bugs naming no model", () => {
  const cited = { models: ["PA-5420"], families: [1] };
  const other = { models: ["PA-5410"], families: [1] };
  const family = { models: [], families: [1] };
  const generic = { models: [], families: [] };
  const elsewhere = { models: [], families: [2] };
  assert.strictEqual(logic.hardwareMatch(cited, "m:PA-5420", families, familyOf), "cited");
  assert.strictEqual(logic.hardwareMatch(other, "m:PA-5420", families, familyOf), null);
  assert.strictEqual(logic.hardwareMatch(family, "m:PA-5420", families, familyOf), "family");
  assert.strictEqual(logic.hardwareMatch(generic, "m:PA-5420", families, familyOf), "generic");
  assert.strictEqual(logic.hardwareMatch(elsewhere, "m:PA-5420", families, familyOf), null);
  assert.strictEqual(logic.hardwareMatch(other, "f:PA-5400 Series", families, familyOf), "family");
});

test("an issue is found by its ID, with or without prefix, and a model stays a keyword", () => {
  const prefixes = new Set(["pan", "wf500"]);
  const bug = { id: "PAN-338608", text: "pan-338608 ospfv3 routes pa-5420" };
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("PAN-338608"), prefixes));
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("338608, OSPFv3"), prefixes));
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("PA-5420"), prefixes));
  assert.ok(!logic.matchesTerms(bug, logic.searchTerms("WF500-338608"), prefixes));
  assert.ok(!logic.matchesTerms(bug, logic.searchTerms("338609"), prefixes));
});

test("an upgrade crosses the first release of each branch, then the target branch", () => {
  assert.deepStrictEqual(logic.upgradePath(versions, at("11.1.4"), at("11.2.14")).map((i) => names[i]),
    ["11.2.12", "11.2.13", "11.2.13-h1", "11.2.13-h3", "11.2.14"]);
  assert.deepStrictEqual(logic.upgradePath(versions, at("11.1.4"), at("12.1.2")).map((i) => names[i]), ["11.2.12", "12.1.2"]);
  assert.deepStrictEqual(logic.upgradePath(versions, at("12.1.2"), at("11.1.4")), []);
});

test("the reading list gives the pages of the crossed branches, target first", () => {
  const pages = { "11.2": { changes: 3, limitations: 4 }, "12.1": { changes: 7 } };
  assert.deepStrictEqual(logic.upgradeReading(pages, versions, at("11.1.4"), at("12.1.2")), [
    { branch: "12.1", kind: "changes", page: 7 },
    { branch: "11.2", kind: "changes", page: 3 },
    { branch: "11.2", kind: "limitations", page: 4 },
  ]);
});

test("upgrade groups put new and remaining issues apart from fixes", () => {
  const introduced = { events: [[at("11.2.14"), "k"]] };
  const remaining = { events: [[at("11.2.12"), "k"], [at("11.2.14"), "k"]] };
  const gained = { events: [[at("11.2.12"), "k"], [at("11.2.14"), "r"]] };
  assert.strictEqual(logic.upgradeGroup(introduced, at("11.2.12"), at("11.2.14"), versions), "introduced");
  assert.strictEqual(logic.upgradeGroup(remaining, at("11.2.12"), at("11.2.14"), versions), "remaining");
  assert.strictEqual(logic.upgradeGroup(gained, at("11.2.12"), at("11.2.14"), versions), "gained");
});

test("support uses the standard date, and tells the extended one", () => {
  const branches = { "10.2": { support: "2025-08-27", extended: "2027-03-31" }, "11.2": { support: "2027-05-02", extended: null } };
  assert.deepStrictEqual([logic.branchSupport("10.2", branches, "2026-11-09").supported, logic.branchSupport("10.2", branches, "2026-11-09").inExtended], [false, true]);
  assert.ok(logic.branchSupport("11.2", branches, "2026-11-09").supported);
  assert.ok(logic.branchSupport("12.2", branches, "2026-11-09").supported);
  assert.ok(!logic.branchSupport("9.1", branches, "2026-11-09").supported);
});

test("a copied table is tab-separated", () => {
  assert.strictEqual(logic.tableText([["ID", "Text"], ["PAN-1", "a\nb"]]), "ID\tText\nPAN-1\ta b");
});
