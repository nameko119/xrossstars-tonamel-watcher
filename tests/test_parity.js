/**
 * JS版の検索が Python版と同じ結果を返すか確かめる。
 * 単体では動かず、tests/test_parity.py から呼ばれる。
 *
 *   node tests/test_parity.js <正規化済みデータ.json> <クエリ.json> <期待値.json>
 */
"use strict";

const fs = require("fs");
const path = require("path");

const XSSearch = require(path.join(__dirname, "..", "bot", "search.js"));

const [dataPath, queryPath, expectedPath] = process.argv.slice(2);
const comps = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const cases = JSON.parse(fs.readFileSync(queryPath, "utf8"));
const expected = JSON.parse(fs.readFileSync(expectedPath, "utf8"));

const TODAY = expected.today;
let failures = 0;

for (const c of cases) {
  const got = XSSearch.search(comps, c.query, TODAY).map((x) => x.id);
  const want = expected.results[c.name];
  if (JSON.stringify(got) === JSON.stringify(want)) {
    console.log(`  ✅ ${c.name}`);
  } else {
    console.log(`  ❌ ${c.name}\n      Python: ${JSON.stringify(want)}\n      JS    : ${JSON.stringify(got)}`);
    failures++;
  }
  const gotCount = XSSearch.count(comps, c.query, TODAY);
  const wantCount = expected.counts[c.name];
  if (gotCount !== wantCount) {
    console.log(`  ❌ ${c.name} の件数\n      Python: ${wantCount}\n      JS    : ${gotCount}`);
    failures++;
  }
}

// 期間の近道指定も一致するか
for (const [name, want] of Object.entries(expected.periods)) {
  const got = XSSearch.periodRange(name, TODAY);
  if (JSON.stringify(got) === JSON.stringify(want)) {
    console.log(`  ✅ 期間「${name}」`);
  } else {
    console.log(`  ❌ 期間「${name}」\n      Python: ${JSON.stringify(want)}\n      JS    : ${JSON.stringify(got)}`);
    failures++;
  }
}

if (failures) {
  console.log(`\n❌ JS/Python で ${failures}件 食い違いました`);
  process.exit(1);
}
console.log("\n✅ JS版とPython版の結果が完全に一致しました");
