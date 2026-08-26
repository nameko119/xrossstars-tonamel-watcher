/* ==========================================================================
 * このファイルは自動生成です。直接編集しないでください。
 *   もと: bot/search.js + bot/worker.js
 *   作り直す: python -m src.build_bot
 *
 * Cloudflare Workers の編集画面に、このファイルの中身をすべて貼り付けます。
 * ========================================================================== */

/**
 * 大会の絞り込みロジック（JavaScript版）。
 *
 * このファイルは Web ページ（docs/index.html）と Discord bot（Cloudflare Worker）の
 * 両方に、そのまま連結して埋め込まれる。import / export を使っていないのはそのため。
 *
 * Python版（src/search.py）と同じ結果になるよう作ってあり、
 * tests/test_parity.js で両者の結果が一致することを確認している。
 * 片方だけ直すとズレるので、条件を変えるときは必ず両方直すこと。
 */
const XSSearch = (() => {
  "use strict";

  const REGIONS = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"],
    "関西": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
  };
  const PREFECTURES = Object.values(REGIONS).flat();
  const SHORT_TO_PREF = {};
  for (const p of PREFECTURES) {
    SHORT_TO_PREF[p] = p;
    if (p !== "北海道") SHORT_TO_PREF[p.replace(/[都道府県]$/, "")] = p;
  }

  /** 比較用に文字列をならす（全角/半角・大文字小文字・連続空白を吸収）。 */
  function fold(text) {
    if (!text) return "";
    return String(text).normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
  }

  /** 開催日を "YYYY-MM-DD" で返す。分からなければ null。 */
  function eventDate(c) {
    if (c.start_at) {
      const m = String(c.start_at).match(/^(\d{4}-\d{2}-\d{2})/);
      if (m) return m[1];
    }
    if (c.start_date && /^\d{4}-\d{2}-\d{2}$/.test(c.start_date)) return c.start_date;
    return null;
  }

  function searchableText(c) {
    return fold([c.title, c.venue, c.address, c.organizer, c.prefecture, c.region,
      c.format, c.id].filter(Boolean).join(" "));
  }

  function resolvePrefecture(name) {
    const n = fold(name).replace(/ /g, "");
    for (const [short, pref] of Object.entries(SHORT_TO_PREF)) {
      if (fold(short) === n) return pref;
    }
    return name;
  }

  /**
   * 1件が条件に合うか。
   * q は src/search.py の Query と同じ形の素のオブジェクト。
   */
  function matches(c, q, today) {
    const d = eventDate(c);

    if (d === null) {
      if (q.include_undated === false) return false;
      if (q.date_from || q.date_to) return false;   // 期間指定時は日付不明を除く
    } else {
      if (!q.include_past && d < today) return false;
      if (q.date_from && d < q.date_from) return false;
      if (q.date_to && d > q.date_to) return false;
    }

    if (q.online === true || q.online === false) {
      if (c.is_online !== q.online) return false;
    }

    if (q.prefectures && q.prefectures.length) {
      const wanted = q.prefectures.map(resolvePrefecture);
      if (!wanted.includes(c.prefecture)) return false;
    }
    if (q.region && c.region !== q.region) return false;

    if (q.capacity_min != null) {
      if (c.capacity_num == null || c.capacity_num < q.capacity_min) return false;
    }
    if (q.capacity_max != null) {
      if (c.capacity_num == null || c.capacity_num > q.capacity_max) return false;
    }
    if (q.fee_max != null) {
      if (c.fee_num == null || c.fee_num > q.fee_max) return false;
    }
    if (q.organizer && !fold(c.organizer).includes(fold(q.organizer))) return false;

    if (q.text) {
      const hay = searchableText(c);
      for (const word of fold(q.text).split(" ")) {
        if (word && !hay.includes(word)) return false;
      }
    }
    return true;
  }

  const FAR_FUTURE = "9999-12-31";
  const FAR_PAST = "0000-01-01";

  function compare(a, b, mode) {
    if (mode === "title") {
      const ta = fold(a.title), tb = fold(b.title);
      if (ta !== tb) return ta < tb ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    if (mode === "added") {
      const aa = a.first_seen || "", bb = b.first_seen || "";
      if (aa !== bb) return aa < bb ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    const far = mode === "-date" ? FAR_PAST : FAR_FUTURE;
    const da = eventDate(a) || far, db = eventDate(b) || far;
    if (da !== db) return da < db ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  }

  /** 条件に合う大会を並べ替えて返す。limit/offset は 0 で無制限。 */
  function search(competitions, q, today) {
    q = q || {};
    today = today || new Date().toISOString().slice(0, 10);
    let hits = competitions.filter((c) => matches(c, q, today));
    const mode = q.sort || "date";
    hits.sort((a, b) => compare(a, b, mode));
    if (mode === "-date") hits.reverse();
    if (q.offset) hits = hits.slice(q.offset);
    if (q.limit) hits = hits.slice(0, q.limit);
    return hits;
  }

  function count(competitions, q, today) {
    today = today || new Date().toISOString().slice(0, 10);
    return competitions.filter((c) => matches(c, q || {}, today)).length;
  }

  // --- 期間の近道指定 ------------------------------------------------------
  function ymd(date) {
    return date.toISOString().slice(0, 10);
  }
  function addDays(iso, days) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + days);
    return ymd(d);
  }
  function weekday(iso) {          // 月曜=0 … 日曜=6
    return (new Date(iso + "T00:00:00Z").getUTCDay() + 6) % 7;
  }

  const PERIOD_CHOICES = ["今日", "明日", "今週末", "今週", "来週", "今月", "来月", "30日以内"];

  /** 「今週末」などを [date_from, date_to] に変換する。該当なしは ["", ""]。 */
  function periodRange(name, today) {
    today = today || ymd(new Date());
    const firstOfMonth = today.slice(0, 8) + "01";
    const nextMonthFirst = (() => {
      const d = new Date(firstOfMonth + "T00:00:00Z");
      d.setUTCMonth(d.getUTCMonth() + 1);
      return ymd(d);
    })();
    switch (name) {
      case "今日": case "today":
        return [today, today];
      case "明日": case "tomorrow": {
        const d = addDays(today, 1);
        return [d, d];
      }
      case "今週末": case "週末": case "weekend": {
        const sat = addDays(today, (5 - weekday(today) + 7) % 7);
        return [sat, addDays(sat, 1)];
      }
      case "今週": case "week": {
        const mon = addDays(today, -weekday(today));
        return [mon > today ? mon : today, addDays(mon, 6)];
      }
      case "来週": case "next_week": {
        const mon = addDays(today, -weekday(today) + 7);
        return [mon, addDays(mon, 6)];
      }
      case "今月": case "month":
        return [firstOfMonth > today ? firstOfMonth : today, addDays(nextMonthFirst, -1)];
      case "来月": case "next_month": {
        const d = new Date(nextMonthFirst + "T00:00:00Z");
        d.setUTCMonth(d.getUTCMonth() + 1);
        return [nextMonthFirst, addDays(ymd(d), -1)];
      }
      case "30日以内": case "30days":
        return [today, addDays(today, 30)];
      default:
        return ["", ""];
    }
  }

  return {
    REGIONS, PREFECTURES, PERIOD_CHOICES,
    fold, eventDate, searchableText, resolvePrefecture,
    matches, search, count, periodRange, addDays,
  };
})();

/**
 * Discord スラッシュコマンド用の Cloudflare Worker。
 *
 * 常時起動のサーバーは要らない。Discordは「Interactions Endpoint URL」に
 * 設定したURLへ、コマンドが叩かれた瞬間だけPOSTしてくる。
 * このWorkerはそれを受けて、GitHub上の大会JSONを読み、絞り込んで返すだけ。
 *
 * 必要な環境変数（Cloudflareの画面で設定する）:
 *   DISCORD_PUBLIC_KEY  Discord Developer Portal の Public Key（必須）
 *   DATA_URL            known_competitions.json の raw URL（必須）
 *   SITE_URL            Webページ（GitHub Pages）のURL（任意・あると便利）
 *
 * ※ このファイル単体では動かない。bot/search.js と連結した
 *    bot/worker.bundle.js を Cloudflare に貼り付けること。
 *    （`python -m src.build_bot` で生成される）
 */
"use strict";

const PER_PAGE = 8;
const CACHE_SECONDS = 300;

const COLOR = 0x3446c4;
const WD = ["月", "火", "水", "木", "金", "土", "日"];

// ---------------------------------------------------------------- 署名の検証
let keyCache = null;

function hexToBytes(hex) {
  const clean = (hex || "").trim();
  if (clean.length % 2 !== 0 || /[^0-9a-fA-F]/.test(clean)) return null;
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
  return out;
}

async function getKey(publicKeyHex) {
  if (keyCache && keyCache.hex === publicKeyHex) return keyCache;
  const raw = hexToBytes(publicKeyHex);
  if (!raw || raw.length !== 32) throw new Error("DISCORD_PUBLIC_KEY の形式が正しくありません");
  // ランタイムによって名前が違うので両方試す
  const candidates = [{ name: "Ed25519" }, { name: "NODE-ED25519", namedCurve: "NODE-ED25519" }];
  let lastError = null;
  for (const algo of candidates) {
    try {
      const key = await crypto.subtle.importKey("raw", raw, algo, false, ["verify"]);
      keyCache = { hex: publicKeyHex, key, algo };
      return keyCache;
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError || new Error("Ed25519 に対応していません");
}

async function verifyRequest(request, bodyText, publicKeyHex) {
  const sig = request.headers.get("x-signature-ed25519");
  const ts = request.headers.get("x-signature-timestamp");
  if (!sig || !ts) return false;
  const sigBytes = hexToBytes(sig);
  if (!sigBytes) return false;
  const { key, algo } = await getKey(publicKeyHex);
  const message = new TextEncoder().encode(ts + bodyText);
  try {
    return await crypto.subtle.verify(algo, key, sigBytes, message);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- データ取得
async function loadCompetitions(dataUrl) {
  const res = await fetch(dataUrl, {
    headers: { "User-Agent": "xrossstars-tonamel-watcher-bot/1.0" },
    cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
  });
  if (!res.ok) throw new Error(`大会データを読めませんでした (HTTP ${res.status})`);
  const json = await res.json();
  const raw = json && json.competitions ? json.competitions : {};
  return Array.isArray(raw) ? raw : Object.values(raw);
}

// ---------------------------------------------------------------- 表示の組み立て
function todayJST() {
  // JSTの「今日」。Workerの時計はUTCなので9時間ずらして日付だけ取る
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

function formatWhen(c) {
  const iso = XSSearch.eventDate(c);
  if (!iso) return "日程未定";
  const [y, m, d] = iso.split("-");
  const wd = WD[(new Date(iso + "T00:00:00Z").getUTCDay() + 6) % 7];
  let time = "";
  if (c.start_at) {
    const t = String(c.start_at).match(/T(\d{2}):(\d{2})/);
    if (t) time = ` ${t[1]}:${t[2]}`;
  }
  return `${y}/${m}/${d}(${wd})${time || " 時刻未定"}`;
}

function formatPlace(c) {
  if (c.is_online === true) return "オンライン";
  const bits = [c.prefecture, c.venue].filter(Boolean);
  return bits.length ? bits.join(" ") : (c.format || "会場未定");
}

function formatFee(c) {
  if (c.fee_num === 0) return "無料";
  if (c.fee_num != null) return `${c.fee_num.toLocaleString("ja-JP")}円`;
  return c.entry_fee || "参加費不明";
}

function formatCapacity(c) {
  if (c.capacity_num != null) return `定員${c.capacity_num}人`;
  return c.capacity ? `定員${c.capacity}` : "";
}

function line(c) {
  const meta = [formatPlace(c), formatFee(c), formatCapacity(c)].filter(Boolean).join(" ・ ");
  const title = (c.title || "(タイトル不明)").replace(/[[\]()]/g, "");
  return `**${formatWhen(c)}**\n[${title}](${c.url})\n${meta}`;
}

function describeQuery(q, period) {
  const bits = [];
  if (q.text) bits.push(`「${q.text}」`);
  if (period) bits.push(period);
  else if (q.date_from || q.date_to) bits.push(`${q.date_from || "…"}〜${q.date_to || "…"}`);
  if (q.online === true) bits.push("オンライン");
  if (q.online === false) bits.push("オフライン");
  if (q.prefectures && q.prefectures.length) bits.push(q.prefectures.join("・"));
  if (q.region) bits.push(q.region);
  if (q.organizer) bits.push(`主催:${q.organizer}`);
  if (q.capacity_min != null) bits.push(`定員${q.capacity_min}人以上`);
  if (q.capacity_max != null) bits.push(`定員${q.capacity_max}人以下`);
  if (q.fee_max === 0) bits.push("無料");
  else if (q.fee_max != null) bits.push(`${q.fee_max}円以下`);
  if (q.include_past) bits.push("過去も表示");
  return bits.length ? bits.join(" / ") : "条件なし";
}

function siteLink(siteUrl, q, period) {
  if (!siteUrl) return null;
  const p = new URLSearchParams();
  if (q.text) p.set("q", q.text);
  if (q.online === true) p.set("mode", "online");
  if (q.online === false) p.set("mode", "offline");
  if (period) p.set("period", period);
  if (q.region) p.set("region", q.region);
  if (q.prefectures && q.prefectures.length) p.set("pref", q.prefectures[0]);
  if (q.organizer) p.set("org", q.organizer);
  if (q.capacity_min != null) p.set("capmin", q.capacity_min);
  if (q.capacity_max != null) p.set("capmax", q.capacity_max);
  if (q.fee_max === 0) p.set("free", "1");
  else if (q.fee_max != null) p.set("feemax", q.fee_max);
  if (q.date_from) p.set("from", q.date_from);
  if (q.date_to) p.set("to", q.date_to);
  if (q.include_past) p.set("past", "1");
  const s = p.toString();
  return s ? `${siteUrl}#${s}` : siteUrl;
}

/** ページ送りボタンに載せる条件。custom_id は100文字までなので詰めて入れる。 */
function encodeState(q, period, page) {
  const p = new URLSearchParams();
  if (q.text) p.set("t", q.text);
  if (q.online === true) p.set("o", "1");
  if (q.online === false) p.set("o", "0");
  if (period) p.set("pd", period);
  if (q.region) p.set("rg", q.region);
  if (q.prefectures && q.prefectures.length) p.set("pf", q.prefectures[0]);
  if (q.organizer) p.set("og", q.organizer);
  if (q.capacity_min != null) p.set("cn", q.capacity_min);
  if (q.capacity_max != null) p.set("cx", q.capacity_max);
  if (q.fee_max != null) p.set("fx", q.fee_max);
  if (q.date_from) p.set("df", q.date_from);
  if (q.date_to) p.set("dt", q.date_to);
  if (q.include_past) p.set("ps", "1");
  if (q.sort && q.sort !== "date") p.set("s", q.sort);
  p.set("p", String(page));
  return "xs:" + p.toString();
}

function decodeState(customId) {
  const p = new URLSearchParams(String(customId).replace(/^xs:/, ""));
  const q = {
    text: p.get("t") || "",
    region: p.get("rg") || "",
    prefectures: p.get("pf") ? [p.get("pf")] : [],
    organizer: p.get("og") || "",
    capacity_min: p.has("cn") ? Number(p.get("cn")) : null,
    capacity_max: p.has("cx") ? Number(p.get("cx")) : null,
    fee_max: p.has("fx") ? Number(p.get("fx")) : null,
    include_past: p.get("ps") === "1",
    sort: p.get("s") || "date",
    date_from: p.get("df") || "",
    date_to: p.get("dt") || "",
  };
  if (p.get("o") === "1") q.online = true;
  if (p.get("o") === "0") q.online = false;
  return { q, period: p.get("pd") || "", page: Math.max(0, Number(p.get("p")) || 0) };
}

function buildMessage(comps, q, period, page, siteUrl, heading) {
  const today = todayJST();
  const hits = XSSearch.search(comps, q, today);
  const pages = Math.max(1, Math.ceil(hits.length / PER_PAGE));
  page = Math.min(Math.max(0, page), pages - 1);
  const slice = hits.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE);

  const embed = {
    title: `${heading} ${hits.length}件`,
    color: COLOR,
    description: slice.length
      ? slice.map(line).join("\n\n")
      : "条件に合う大会はありませんでした。キーワードを短くするか、条件を減らしてみてください。",
    footer: { text: `条件: ${describeQuery(q, period)}　|　${page + 1} / ${pages} ページ` },
  };

  const components = [];
  const state = encodeState(q, period, page);
  const row = { type: 1, components: [] };
  // custom_id は100文字まで。長すぎる条件のときはページ送りを諦めてWebに誘導する
  const canPaginate = pages > 1 && state.length <= 90;
  if (canPaginate) {
    row.components.push({
      type: 2, style: 2, label: "◀ 前へ",
      custom_id: encodeState(q, period, page - 1),
      disabled: page === 0,
    });
    row.components.push({
      type: 2, style: 2, label: "次へ ▶",
      custom_id: encodeState(q, period, page + 1),
      disabled: page >= pages - 1,
    });
  }
  const url = siteLink(siteUrl, q, period);
  if (url) row.components.push({ type: 2, style: 5, label: "Webで見る", url });
  if (row.components.length) components.push(row);

  if (pages > 1 && !canPaginate) {
    embed.footer.text += "　|　条件が長いためページ送りは使えません";
  }

  return { embeds: [embed], components };
}

// ---------------------------------------------------------------- コマンド解釈
function optionMap(options) {
  const m = {};
  for (const o of options || []) m[o.name] = o.value;
  return m;
}

function queryFromOptions(opts) {
  const q = {
    text: opts.keyword || "",
    region: opts.region || "",
    prefectures: opts.prefecture ? [opts.prefecture] : [],
    organizer: opts.organizer || "",
    capacity_min: opts.min_capacity != null ? Number(opts.min_capacity) : null,
    capacity_max: opts.max_capacity != null ? Number(opts.max_capacity) : null,
    fee_max: null,
    include_past: opts.include_past === true,
    sort: opts.sort || "date",
    date_from: opts.date_from || "",
    date_to: opts.date_to || "",
  };
  if (opts.format === "online") q.online = true;
  if (opts.format === "offline") q.online = false;
  if (opts.free === true) q.fee_max = 0;
  else if (opts.max_fee != null) q.fee_max = Number(opts.max_fee);

  const period = opts.period || "";
  if (period && !q.date_from && !q.date_to) {
    const [f, t] = XSSearch.periodRange(period, todayJST());
    q.date_from = f;
    q.date_to = t;
  }
  return { q, period };
}

// ---------------------------------------------------------------- 応答の送信
async function editOriginal(appId, token, payload) {
  const url = `https://discord.com/api/v10/webhooks/${appId}/${token}/messages/@original`;
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    console.log("応答の差し替えに失敗:", res.status, await res.text());
  }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function respondLater(interaction, env) {
  const appId = interaction.application_id;
  const token = interaction.token;
  try {
    const comps = await loadCompetitions(env.DATA_URL);
    let payload;
    if (interaction.type === 3) {
      const { q, period, page } = decodeState(interaction.data.custom_id);
      payload = buildMessage(comps, q, period, page, env.SITE_URL, "🔎 検索結果");
    } else {
      const name = interaction.data.name;
      const opts = optionMap(interaction.data.options);
      const { q, period } = queryFromOptions(opts);
      const heading = name === "list" || name === "一覧" ? "📋 大会一覧" : "🔎 検索結果";
      payload = buildMessage(comps, q, period, 0, env.SITE_URL, heading);
    }
    await editOriginal(appId, token, payload);
  } catch (e) {
    await editOriginal(appId, token, {
      content: `⚠️ うまく取得できませんでした: ${e.message}`,
    });
  }
}

// ---------------------------------------------------------------- 入口
export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      // 動作確認用。ブラウザで開くとこれが出れば、Workerは生きている
      return new Response(
        "Xrossstars 大会bot は動作しています。DiscordのInteractions Endpoint URLに" +
        "このURLを設定してください。",
        { headers: { "Content-Type": "text/plain; charset=utf-8" } },
      );
    }
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }
    if (!env.DISCORD_PUBLIC_KEY || !env.DATA_URL) {
      return new Response("環境変数 DISCORD_PUBLIC_KEY / DATA_URL が未設定です", { status: 500 });
    }

    const bodyText = await request.text();
    let ok = false;
    try {
      ok = await verifyRequest(request, bodyText, env.DISCORD_PUBLIC_KEY);
    } catch (e) {
      return new Response(`署名の検証に失敗しました: ${e.message}`, { status: 500 });
    }
    if (!ok) return new Response("invalid request signature", { status: 401 });

    let interaction;
    try {
      interaction = JSON.parse(bodyText);
    } catch {
      return new Response("bad request", { status: 400 });
    }

    // 1 = PING（エンドポイント登録時の疎通確認）
    if (interaction.type === 1) return json({ type: 1 });

    // 2 = スラッシュコマンド, 3 = ボタン
    if (interaction.type === 2 || interaction.type === 3) {
      // 先に「考え中…」を返し、データ取得を待たせない（3秒制限を確実に回避する）
      const deferType = interaction.type === 2 ? 5 : 6;
      ctx.waitUntil(respondLater(interaction, env));
      return json({ type: deferType });
    }

    return json({ type: 4, data: { content: "対応していない操作です。" } });
  },
};
