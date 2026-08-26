"""大会DBから、一覧・検索できる1枚のHTMLを組み立てる。

生成物は docs/index.html。GitHub Pages で公開すればスマホからも見られる。
データはHTMLに直接埋め込むので、サーバーもAPIも要らず、
絞り込みはすべて閲覧者の端末の中だけで完結する。

絞り込みロジックは bot/search.js をそのまま埋め込んで使う。
Discord bot と同じコードなので、両者で結果がズレることがない。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config as C
from .models import Competition

ROOT = Path(__file__).resolve().parent.parent
SEARCH_JS_PATH = ROOT / "bot" / "search.js"
SITE_DIR = ROOT / "docs"
SITE_PATH = SITE_DIR / "index.html"

PAGE_TITLE = "Xrossstars 大会ファインダー"

# 閲覧側に渡すのは表示と絞り込みに使う項目だけ。生HTMLなどは載せない。
EXPORT_FIELDS = (
    "id", "url", "title", "start_at", "end_at", "start_date", "format", "venue",
    "address",
    "organizer", "entry_fee", "capacity", "entry_period", "prefecture", "region",
    "capacity_num", "fee_num", "is_online", "first_seen",
)


def export_competitions(competitions: list[Competition]) -> list[dict]:
    out = []
    for c in competitions:
        d = c.to_dict()
        out.append({k: d.get(k) for k in EXPORT_FIELDS})
    return out


STYLE = """
:root {
  color-scheme: light dark;

  /* 夜空の藍を軸にした配色。中間色もすべて藍寄りに振っている */
  --ground: #f5f6fa;
  --surface: #ffffff;
  --surface-2: #eef0f7;
  --ink: #171a2b;
  --ink-soft: #464c66;
  --muted: #5c6480;
  --line: #dde1ee;
  --line-strong: #c3c9de;
  --accent: #3446c4;
  --accent-ink: #ffffff;
  --accent-soft: #e6e9fb;

  /* 開催形式の状態色。アクセントとは別系統にして役割を混ぜない */
  --online: #0b6b74;
  --online-bg: #dcf0f2;
  --offline: #8f5806;
  --offline-bg: #f8ebd6;

  --radius: 10px;
  --shadow: 0 1px 2px rgba(23, 26, 43, .06), 0 8px 24px -16px rgba(23, 26, 43, .3);

  --font-display: "Shippori Mincho B1", "Hiragino Mincho ProN", "Yu Mincho", serif;
  --font-body: "Zen Kaku Gothic New", "Hiragino Sans", "Yu Gothic", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0e1020;
    --surface: #171a2e;
    --surface-2: #1e2239;
    --ink: #e9ebf6;
    --ink-soft: #c3c8de;
    --muted: #969dbb;
    --line: #262b45;
    --line-strong: #394061;
    --accent: #8f9cff;
    --accent-ink: #10132a;
    --accent-soft: #232a52;
    --online: #6fd6e2;
    --online-bg: #10333a;
    --offline: #f0b95f;
    --offline-bg: #3a2c12;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px -16px rgba(0, 0, 0, .8);
  }
}

:root[data-theme="dark"] {
  --ground: #0e1020;
  --surface: #171a2e;
  --surface-2: #1e2239;
  --ink: #e9ebf6;
  --ink-soft: #c3c8de;
  --muted: #969dbb;
  --line: #262b45;
  --line-strong: #394061;
  --accent: #8f9cff;
  --accent-ink: #10132a;
  --accent-soft: #232a52;
  --online: #6fd6e2;
  --online-bg: #10333a;
  --offline: #f0b95f;
  --offline-bg: #3a2c12;
  --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px -16px rgba(0, 0, 0, .8);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 15px;
  line-height: 1.7;
  -webkit-text-size-adjust: 100%;
}

.wrap { max-width: 860px; margin: 0 auto; padding: 0 16px 64px; }

/* ---------------------------------------------------------------- 見出し */
.masthead {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px;
  padding: 28px 0 18px;
  border-bottom: 2px solid var(--ink);
}
.masthead h1 {
  font-family: var(--font-display);
  font-size: clamp(24px, 5vw, 34px);
  font-weight: 700; letter-spacing: .02em; margin: 0;
  text-wrap: balance;
}
.masthead .sub { color: var(--muted); font-size: 13px; margin: 0; }
.masthead .stamp {
  margin-left: auto; font-family: var(--font-mono); font-size: 12px;
  color: var(--muted); font-variant-numeric: tabular-nums;
}

/* ---------------------------------------------------------------- 絞り込み */
.controls {
  position: sticky; top: 0; z-index: 5;
  background: var(--ground);
  padding: 14px 0 12px;
  border-bottom: 1px solid var(--line);
  display: flex; flex-direction: column; gap: 10px;
}
.searchbar { display: flex; gap: 8px; }
.searchbar input[type="search"] {
  flex: 1; min-width: 0;
  font: inherit; color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line-strong); border-radius: var(--radius);
  padding: 10px 12px;
}
.searchbar input[type="search"]::placeholder { color: var(--muted); }

.chiprow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chiprow .label {
  font-size: 11px; letter-spacing: .12em; color: var(--muted);
  text-transform: uppercase; margin-right: 2px;
}
.chip {
  font: inherit; font-size: 13px; line-height: 1;
  padding: 7px 12px; border-radius: 999px;
  border: 1px solid var(--line-strong); background: var(--surface);
  color: var(--ink-soft); cursor: pointer;
}
.chip:hover { border-color: var(--accent); color: var(--accent); }
.chip[aria-pressed="true"] {
  background: var(--accent); border-color: var(--accent); color: var(--accent-ink);
  font-weight: 700;
}

details.advanced { border-top: 1px dashed var(--line-strong); padding-top: 10px; }
details.advanced > summary {
  cursor: pointer; font-size: 13px; color: var(--accent);
  list-style: none; display: inline-flex; align-items: center; gap: 6px;
}
details.advanced > summary::-webkit-details-marker { display: none; }
details.advanced > summary::before { content: "＋"; font-family: var(--font-mono); }
details.advanced[open] > summary::before { content: "−"; }

.grid {
  display: grid; gap: 10px 14px; margin-top: 12px;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}
.field { display: flex; flex-direction: column; gap: 4px; }
.field > span { font-size: 11px; letter-spacing: .1em; color: var(--muted); }
.field select, .field input {
  font: inherit; font-size: 14px; color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line-strong); border-radius: 8px; padding: 8px 10px;
  min-width: 0;
}
.field .pair { display: flex; align-items: center; gap: 6px; }
.field .pair input { width: 100%; font-family: var(--font-mono); }
.toggles { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; font-size: 13px; }
.toggles label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }

/* ---------------------------------------------------------------- 結果 */
.resultbar {
  display: flex; align-items: baseline; gap: 12px;
  padding: 18px 0 6px;
}
.resultbar .count {
  font-family: var(--font-mono); font-size: 20px; font-variant-numeric: tabular-nums;
}
.resultbar .of { color: var(--muted); font-size: 13px; }
.resultbar .reset {
  margin-left: auto; font: inherit; font-size: 13px;
  background: none; border: 0; color: var(--accent); cursor: pointer;
  text-decoration: underline; text-underline-offset: 3px; padding: 4px;
}

.monthhead {
  position: sticky; top: 0; z-index: 1;
  font-family: var(--font-mono); font-size: 12px; letter-spacing: .1em;
  color: var(--muted); background: var(--ground);
  padding: 14px 0 6px; border-bottom: 1px solid var(--line);
  margin-bottom: 10px;
}

.cards { display: flex; flex-direction: column; gap: 10px; }

.card {
  display: grid; grid-template-columns: 64px 1fr; gap: 0 14px;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 14px; text-decoration: none; color: inherit;
}
.card:hover { border-color: var(--accent); }
.card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.rail {
  display: flex; flex-direction: column; align-items: center; justify-content: flex-start;
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  border-right: 1px solid var(--line); padding-right: 12px; line-height: 1.2;
}
.rail .day { font-size: 26px; font-weight: 700; }
.rail .wd { font-size: 11px; color: var(--muted); }
.rail .time { font-size: 11px; color: var(--muted); margin-top: 4px; }
.rail.unknown .day { font-size: 13px; font-weight: 400; color: var(--muted); padding-top: 6px; }

.body h3 {
  margin: 0 0 6px; font-size: 16px; font-weight: 700; line-height: 1.45;
  text-wrap: balance;
}
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.tag {
  font-size: 11.5px; line-height: 1; padding: 5px 8px; border-radius: 6px;
  background: var(--surface-2); color: var(--ink-soft);
}
.tag.online { background: var(--online-bg); color: var(--online); font-weight: 700; }
.tag.offline { background: var(--offline-bg); color: var(--offline); font-weight: 700; }
.tag.free { border: 1px solid currentColor; }
.meta { font-size: 12.5px; color: var(--muted); }
.meta .sep { opacity: .5; margin: 0 6px; }

.empty {
  text-align: center; padding: 48px 16px; color: var(--muted);
  border: 1px dashed var(--line-strong); border-radius: var(--radius);
}
.empty strong { display: block; color: var(--ink); font-size: 16px; margin-bottom: 6px; }

footer {
  margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line);
  font-size: 12px; color: var(--muted);
}
footer a { color: var(--accent); }

@media (max-width: 560px) {
  .card { grid-template-columns: 1fr; gap: 8px; }
  .rail {
    flex-direction: row; align-items: baseline; gap: 8px;
    border-right: 0; border-bottom: 1px solid var(--line);
    padding: 0 0 8px; justify-content: flex-start;
  }
  .rail .day { font-size: 20px; }
  .rail.unknown .day { padding-top: 0; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""

BODY = """
<div class="wrap">
  <header class="masthead">
    <div>
      <h1>Xrossstars 大会ファインダー</h1>
      <p class="sub">Tonamel に掲載された自主大会・店舗大会を自動で集めています</p>
    </div>
    <div class="stamp" id="stamp"></div>
  </header>

  <div class="controls">
    <div class="searchbar">
      <input type="search" id="q" placeholder="大会名・会場・主催者で検索" aria-label="キーワード検索">
    </div>

    <div class="chiprow" role="group" aria-label="開催形式">
      <span class="label">形式</span>
      <button class="chip" type="button" data-mode="all" aria-pressed="true">すべて</button>
      <button class="chip" type="button" data-mode="online" aria-pressed="false">オンライン</button>
      <button class="chip" type="button" data-mode="offline" aria-pressed="false">オフライン</button>
    </div>

    <div class="chiprow" role="group" aria-label="期間">
      <span class="label">期間</span>
      <button class="chip" type="button" data-period="" aria-pressed="true">すべて</button>
      <button class="chip" type="button" data-period="今週末" aria-pressed="false">今週末</button>
      <button class="chip" type="button" data-period="今月" aria-pressed="false">今月</button>
      <button class="chip" type="button" data-period="来月" aria-pressed="false">来月</button>
      <button class="chip" type="button" data-period="30日以内" aria-pressed="false">30日以内</button>
    </div>

    <details class="advanced" id="advanced">
      <summary>詳細条件</summary>
      <div class="grid">
        <label class="field"><span>地方</span>
          <select id="region"><option value="">指定なし</option></select>
        </label>
        <label class="field"><span>都道府県</span>
          <select id="pref"><option value="">指定なし</option></select>
        </label>
        <label class="field"><span>主催者</span>
          <select id="organizer"><option value="">指定なし</option></select>
        </label>
        <label class="field"><span>定員（人）</span>
          <span class="pair">
            <input type="number" id="capmin" min="0" placeholder="下限" inputmode="numeric">
            <span>〜</span>
            <input type="number" id="capmax" min="0" placeholder="上限" inputmode="numeric">
          </span>
        </label>
        <label class="field"><span>参加費の上限（円）</span>
          <input type="number" id="feemax" min="0" placeholder="指定なし" inputmode="numeric">
        </label>
        <label class="field"><span>開催日</span>
          <span class="pair">
            <input type="date" id="from" aria-label="開催日の開始">
            <span>〜</span>
            <input type="date" id="to" aria-label="開催日の終了">
          </span>
        </label>
        <label class="field"><span>並び替え</span>
          <select id="sort">
            <option value="date">開催日が近い順</option>
            <option value="-date">開催日が遠い順</option>
            <option value="added">新しく見つけた順</option>
            <option value="title">大会名順</option>
          </select>
        </label>
      </div>
      <div class="toggles">
        <label><input type="checkbox" id="free"> 無料のみ</label>
        <label><input type="checkbox" id="past"> 終了した大会も表示</label>
      </div>
    </details>
  </div>

  <div class="resultbar">
    <span class="count" id="count" aria-live="polite">0</span>
    <span class="of" id="total"></span>
    <button class="reset" type="button" id="reset">条件をクリア</button>
  </div>

  <div id="results"></div>

  <footer>
    <p id="footnote"></p>
    <p>
      日時・会場は自動抽出のため誤りが含まれることがあります。参加前に
      <a href="https://tonamel.com/competitions?game=XrossStars&amp;region=JP" target="_blank" rel="noopener">Tonamelの大会ページ</a>
      で必ずご確認ください。
    </p>
  </footer>
</div>
"""

APP_JS = r"""
(function () {
  "use strict";
  const DATA = window.__XS_DATA__;
  const comps = DATA.competitions;
  const TODAY = DATA.today;
  const WD = ["月", "火", "水", "木", "金", "土", "日"];

  const $ = (id) => document.getElementById(id);
  const els = {
    q: $("q"), region: $("region"), pref: $("pref"), organizer: $("organizer"),
    capmin: $("capmin"), capmax: $("capmax"), feemax: $("feemax"),
    from: $("from"), to: $("to"), sort: $("sort"),
    free: $("free"), past: $("past"),
    count: $("count"), total: $("total"), results: $("results"),
    stamp: $("stamp"), footnote: $("footnote"), advanced: $("advanced"),
  };
  let mode = "all";     // all | online | offline
  let period = "";

  // --- 選択肢を実データから作る -------------------------------------------
  function fillOptions() {
    for (const r of Object.keys(XSSearch.REGIONS)) {
      if (comps.some((c) => c.region === r)) add(els.region, r, r);
    }
    const prefs = XSSearch.PREFECTURES.filter((p) => comps.some((c) => c.prefecture === p));
    for (const p of prefs) add(els.pref, p, p);
    const orgs = [...new Set(comps.map((c) => c.organizer).filter(Boolean))].sort();
    for (const o of orgs) add(els.organizer, o, o);
  }
  function add(sel, value, label) {
    const o = document.createElement("option");
    o.value = value; o.textContent = label; sel.appendChild(o);
  }

  // --- 画面の状態 → 検索条件 ----------------------------------------------
  function buildQuery() {
    const q = {
      text: els.q.value.trim(),
      region: els.region.value,
      prefectures: els.pref.value ? [els.pref.value] : [],
      organizer: els.organizer.value,
      capacity_min: numOrNull(els.capmin.value),
      capacity_max: numOrNull(els.capmax.value),
      fee_max: els.free.checked ? 0 : numOrNull(els.feemax.value),
      include_past: els.past.checked,
      sort: els.sort.value,
      date_from: els.from.value,
      date_to: els.to.value,
    };
    if (mode === "online") q.online = true;
    else if (mode === "offline") q.online = false;
    if (period && !q.date_from && !q.date_to) {
      const [f, t] = XSSearch.periodRange(period, TODAY);
      q.date_from = f; q.date_to = t;
    }
    return q;
  }
  const numOrNull = (v) => (v === "" || v == null || isNaN(+v) ? null : +v);

  // --- 描画 ----------------------------------------------------------------
  function fmtFee(c) {
    if (c.fee_num === 0) return "無料";
    if (c.fee_num != null) return c.fee_num.toLocaleString("ja-JP") + "円";
    return c.entry_fee || "";
  }
  function fmtCap(c) {
    if (c.capacity_num != null) return "定員 " + c.capacity_num + "人";
    return c.capacity ? "定員 " + c.capacity : "";
  }
  function dateParts(c) {
    const iso = XSSearch.eventDate(c);
    if (!iso) return null;
    const d = new Date(iso + "T00:00:00+09:00");
    let time = "";
    if (c.start_at) {
      const m = String(c.start_at).match(/T(\d{2}):(\d{2})/);
      if (m) time = m[1] + ":" + m[2];
    }
    return {
      iso, time,
      day: String(d.getDate()),
      wd: WD[(d.getDay() + 6) % 7],
      month: d.getFullYear() + "年" + (d.getMonth() + 1) + "月",
    };
  }

  function render(hits, total) {
    els.count.textContent = hits.length;
    els.total.textContent = hits.length === total ? "件" : "件 / 全" + total + "件中";
    els.results.replaceChildren();

    if (!hits.length) {
      const box = document.createElement("div");
      box.className = "empty";
      box.innerHTML =
        "<strong>条件に合う大会はありません</strong>" +
        "キーワードを短くするか、期間や地域の指定を外してみてください。";
      els.results.appendChild(box);
      return;
    }

    let currentMonth = null;
    let list = null;
    for (const c of hits) {
      const dp = dateParts(c);
      const month = dp ? dp.month : "開催日未定";
      if (month !== currentMonth) {
        currentMonth = month;
        const h = document.createElement("div");
        h.className = "monthhead";
        h.textContent = month;
        els.results.appendChild(h);
        list = document.createElement("div");
        list.className = "cards";
        els.results.appendChild(list);
      }
      list.appendChild(card(c, dp));
    }
  }

  function card(c, dp) {
    const a = document.createElement("a");
    a.className = "card";
    a.href = c.url; a.target = "_blank"; a.rel = "noopener";

    const rail = document.createElement("div");
    rail.className = "rail" + (dp ? "" : " unknown");
    if (dp) {
      rail.innerHTML =
        '<span class="day"></span><span class="wd"></span><span class="time"></span>';
      rail.querySelector(".day").textContent = dp.day;
      rail.querySelector(".wd").textContent = dp.wd;
      rail.querySelector(".time").textContent = dp.time || "時刻未定";
    } else {
      rail.innerHTML = '<span class="day">日程<br>未定</span>';
    }

    const body = document.createElement("div");
    body.className = "body";
    const h3 = document.createElement("h3");
    h3.textContent = c.title || "(タイトル不明)";
    body.appendChild(h3);

    const tags = document.createElement("div");
    tags.className = "tags";
    if (c.is_online === true) tags.appendChild(tag("オンライン", "online"));
    else if (c.is_online === false) tags.appendChild(tag(c.prefecture || "オフライン", "offline"));
    const fee = fmtFee(c);
    if (fee) tags.appendChild(tag(fee, c.fee_num === 0 ? "free" : ""));
    const cap = fmtCap(c);
    if (cap) tags.appendChild(tag(cap, ""));
    if (tags.childElementCount) body.appendChild(tags);

    const meta = document.createElement("div");
    meta.className = "meta";
    const bits = [];
    if (c.venue) bits.push(c.venue);
    // 住所は会場名と重複しないときだけ添える
    if (c.address && !(c.venue && c.address.includes(c.venue))) bits.push(c.address);
    if (c.organizer) bits.push("主催 " + c.organizer);
    meta.innerHTML = bits.map(esc).join('<span class="sep">/</span>');
    if (bits.length) body.appendChild(meta);

    a.append(rail, body);
    return a;
  }
  function tag(text, cls) {
    const s = document.createElement("span");
    s.className = "tag" + (cls ? " " + cls : "");
    s.textContent = text;
    return s;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

  // --- URLに条件を残す（共有・ブックマーク用） -----------------------------
  function toHash(q) {
    const p = new URLSearchParams();
    if (q.text) p.set("q", q.text);
    if (mode !== "all") p.set("mode", mode);
    if (period) p.set("period", period);
    if (q.region) p.set("region", q.region);
    if (q.prefectures.length) p.set("pref", q.prefectures[0]);
    if (q.organizer) p.set("org", q.organizer);
    if (q.capacity_min != null) p.set("capmin", q.capacity_min);
    if (q.capacity_max != null) p.set("capmax", q.capacity_max);
    if (els.free.checked) p.set("free", "1");
    else if (q.fee_max != null) p.set("feemax", q.fee_max);
    if (els.from.value) p.set("from", els.from.value);
    if (els.to.value) p.set("to", els.to.value);
    if (q.sort !== "date") p.set("sort", q.sort);
    if (q.include_past) p.set("past", "1");
    const s = p.toString();
    history.replaceState(null, "", s ? "#" + s : location.pathname);
  }

  /** URLの条件を画面に反映する。条件が無ければ既定の状態に戻す。 */
  function fromHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    els.q.value = p.get("q") || "";
    mode = p.get("mode") || "all";
    period = p.get("period") || "";
    els.region.value = p.get("region") || "";
    els.pref.value = p.get("pref") || "";
    els.organizer.value = p.get("org") || "";
    els.capmin.value = p.get("capmin") || "";
    els.capmax.value = p.get("capmax") || "";
    els.feemax.value = p.get("feemax") || "";
    els.from.value = p.get("from") || "";
    els.to.value = p.get("to") || "";
    els.sort.value = p.get("sort") || "date";
    els.free.checked = p.get("free") === "1";
    els.past.checked = p.get("past") === "1";
    syncChips();
    if ([...p.keys()].some((k) => !["q", "mode", "period"].includes(k))) {
      els.advanced.open = true;
    }
  }

  // 条件つきのリンクを開いたとき（すでにページを開いていても）反映されるように
  window.addEventListener("hashchange", () => { fromHash(); syncChips(); run(); });

  function syncChips() {
    document.querySelectorAll("[data-mode]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
    });
    document.querySelectorAll("[data-period]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.period === period));
    });
  }

  // --- 実行 ----------------------------------------------------------------
  function run() {
    const q = buildQuery();
    const total = XSSearch.count(comps, { include_past: els.past.checked }, TODAY);
    render(XSSearch.search(comps, q, TODAY), total);
    toHash(q);
  }

  function bind() {
    for (const el of [els.q, els.region, els.pref, els.organizer, els.capmin,
                      els.capmax, els.feemax, els.from, els.to, els.sort,
                      els.free, els.past]) {
      el.addEventListener("input", run);
      el.addEventListener("change", run);
    }
    document.querySelectorAll("[data-mode]").forEach((b) => {
      b.addEventListener("click", () => { mode = b.dataset.mode; syncChips(); run(); });
    });
    document.querySelectorAll("[data-period]").forEach((b) => {
      b.addEventListener("click", () => {
        period = b.dataset.period;
        if (period) { els.from.value = ""; els.to.value = ""; }
        syncChips(); run();
      });
    });
    $("reset").addEventListener("click", () => {
      els.q.value = "";
      for (const el of [els.region, els.pref, els.organizer]) el.value = "";
      for (const el of [els.capmin, els.capmax, els.feemax, els.from, els.to]) el.value = "";
      els.sort.value = "date";
      els.free.checked = false; els.past.checked = false;
      mode = "all"; period = "";
      syncChips(); run();
    });
  }

  els.stamp.textContent = "最終更新 " + DATA.generated_at;
  els.footnote.textContent =
    "全" + comps.length + "件を収録。" + DATA.generated_at + " 時点のTonamel掲載情報です。";
  fillOptions();
  fromHash();
  syncChips();
  bind();
  run();
})();
"""

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Shippori+Mincho+B1:wght@700&"
    "family=Zen+Kaku+Gothic+New:wght@400;500;700&"
    'family=JetBrains+Mono:wght@400;700&display=swap">'
)


def build(competitions: list[Competition], fragment: bool = False,
          now: datetime | None = None) -> str:
    now = now or datetime.now(C.JST)
    search_js = SEARCH_JS_PATH.read_text(encoding="utf-8")
    # Node向けの行はブラウザに要らない
    search_js = search_js.replace(
        'if (typeof module !== "undefined" && module.exports) module.exports = XSSearch;', "")

    payload = {
        "generated_at": now.strftime("%Y/%m/%d %H:%M"),
        "today": now.strftime("%Y-%m-%d"),
        "competitions": export_competitions(competitions),
    }
    data_js = "window.__XS_DATA__ = " + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/") + ";"

    head_bits = f'<title>{PAGE_TITLE}</title>\n{FONT_LINK}\n<style>{STYLE}</style>'
    scripts = (f"<script>{data_js}</script>\n"
               f"<script>{search_js}</script>\n"
               f"<script>{APP_JS}</script>")

    if fragment:
        # Artifact用（<!doctype>や<head>は公開時に付くので書かない）
        return f"{head_bits}\n{BODY}\n{scripts}\n"

    return (
        "<!doctype html>\n"
        '<html lang="ja">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="description" content="Tonamelに掲載されたXrossstars（クロススターズ）の'
        '自主大会・店舗大会を検索できる一覧です。">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"{head_bits}\n</head>\n<body>\n{BODY}\n{scripts}\n</body>\n</html>\n"
    )


def write(competitions: list[Competition], path: Path | None = None,
          now: datetime | None = None) -> int:
    path = path or SITE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(competitions, now=now), encoding="utf-8")
    return len(competitions)
