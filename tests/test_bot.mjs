/**
 * Discord bot（Cloudflare Worker）の動作確認。ネットには出ない。
 * tests/test_bot.py から呼ばれる。
 *
 *   node tests/test_bot.mjs <worker.bundle.mjs> <正規化済みデータ.json>
 *
 * 本物のEd25519鍵で署名したリクエストを作り、Workerに投げて
 * 署名検証・PING応答・コマンド応答・ページ送りが正しいか確かめる。
 */
import fs from "node:fs";
import { webcrypto } from "node:crypto";

const [bundlePath, dataPath] = process.argv.slice(2);
const worker = (await import(bundlePath)).default;

const subtle = webcrypto.subtle;
const enc = new TextEncoder();
let failures = 0;

function chk(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(ok ? `  ✅ ${label}` : `  ❌ ${label}\n      期待: ${JSON.stringify(expected)}\n      実際: ${JSON.stringify(actual)}`);
  if (!ok) failures++;
}
function chkTrue(label, cond, note = "") {
  console.log(cond ? `  ✅ ${label}` : `  ❌ ${label}${note ? "  " + note : ""}`);
  if (!cond) failures++;
}

// --- 鍵を作る --------------------------------------------------------------
const pair = await subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const rawPub = new Uint8Array(await subtle.exportKey("raw", pair.publicKey));
const publicKeyHex = [...rawPub].map((b) => b.toString(16).padStart(2, "0")).join("");

async function signedRequest(body, { badSignature = false } = {}) {
  const bodyText = JSON.stringify(body);
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = new Uint8Array(await subtle.sign({ name: "Ed25519" }, pair.privateKey,
    enc.encode(ts + bodyText)));
  let hex = [...sig].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (badSignature) hex = hex.slice(0, -2) + (hex.endsWith("00") ? "11" : "00");
  return new Request("https://bot.example.workers.dev/", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-signature-ed25519": hex,
      "x-signature-timestamp": ts,
    },
    body: bodyText,
  });
}

// --- Discord と GitHub への通信を差し替える --------------------------------
const competitions = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const DATA_URL = "https://raw.githubusercontent.test/data.json";
let sentPayload = null;
let dataFetches = 0;

globalThis.fetch = async (url, init) => {
  const href = typeof url === "string" ? url : url.url;
  if (href === DATA_URL) {
    dataFetches++;
    return new Response(JSON.stringify({ meta: {}, competitions }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }
  if (href.includes("/webhooks/") && init && init.method === "PATCH") {
    sentPayload = JSON.parse(init.body);
    return new Response("{}", { status: 200 });
  }
  return new Response("not found", { status: 404 });
};

const env = { DISCORD_PUBLIC_KEY: publicKeyHex, DATA_URL, SITE_URL: "https://example.github.io/xs/" };
const pending = [];
const ctx = { waitUntil: (p) => pending.push(p) };

async function call(body, opts) {
  sentPayload = null;
  pending.length = 0;
  const res = await worker.fetch(await signedRequest(body, opts), env, ctx);
  await Promise.all(pending);
  return { res, payload: sentPayload };
}

function interaction(name, options, type = 2) {
  return {
    type, application_id: "app123", token: "tok123",
    data: { name, options },
  };
}

// ============================================================ ここからテスト
console.log("Discord bot（Cloudflare Worker）の動作確認");

// 署名まわり
{
  const { res } = await call({ type: 1 });
  chk("PING に PONG を返す", res.status, 200);
  chk("PONG の中身", await res.json(), { type: 1 });
}
{
  const { res } = await call({ type: 1 }, { badSignature: true });
  chk("署名が違うリクエストは401", res.status, 401);
}
{
  const req = new Request("https://bot.example.workers.dev/", { method: "POST", body: "{}" });
  const res = await worker.fetch(req, env, ctx);
  chk("署名ヘッダが無いリクエストも401", res.status, 401);
}
{
  const res = await worker.fetch(new Request("https://bot.example.workers.dev/"), env, ctx);
  chk("GETは動作確認用の案内を返す", res.status, 200);
  chkTrue("案内文が日本語", (await res.text()).includes("動作しています"));
}
{
  const bad = { DISCORD_PUBLIC_KEY: "zzzz", DATA_URL };
  const res = await worker.fetch(await signedRequest({ type: 1 }), bad, ctx);
  chk("鍵が壊れていたら500で理由を返す", res.status, 500);
}

// /list
{
  const { res, payload } = await call(interaction("list", []));
  chk("コマンドはまず「考え中」を返す", (await res.json()).type, 5);
  chkTrue("あとから結果を差し替える", payload !== null);
  chk("見出しと件数", payload.embeds[0].title, "📋 大会一覧 11件");
  chkTrue("1ページ8件", (payload.embeds[0].description.match(/tonamel/g) || []).length === 8);
  chkTrue("ページ表記", payload.embeds[0].footer.text.includes("1 / 2 ページ"));
  chkTrue("Webへのリンクがある",
    payload.components[0].components.some((c) => c.style === 5 && c.url.startsWith("https://example.github.io/xs/")));
  const prev = payload.components[0].components[0];
  chk("最初のページでは「前へ」を押せない", prev.disabled, true);
}
{
  const { payload } = await call(interaction("list", [{ name: "format", value: "online" }]));
  chk("形式で絞れる", payload.embeds[0].title, "📋 大会一覧 3件");
  chkTrue("条件が表示される", payload.embeds[0].footer.text.includes("オンライン"));
  chkTrue("1ページに収まればページ送りボタンは出ない",
    payload.components[0].components.every((c) => c.style === 5));
}

// /search
{
  const { payload } = await call(interaction("search", [{ name: "keyword", value: "初心者" }]));
  chk("キーワード検索", payload.embeds[0].title, "🔎 検索結果 2件");
  chkTrue("大会名が出る", payload.embeds[0].description.includes("オンライン交流会"));
  chkTrue("会場・参加費・定員が出る", payload.embeds[0].description.includes("無料"));
}
{
  const { payload } = await call(interaction("search", [
    { name: "region", value: "関西" }, { name: "max_fee", value: 1500 },
  ]));
  chk("地方と参加費の組み合わせ", payload.embeds[0].title, "🔎 検索結果 2件");
}
{
  const { payload } = await call(interaction("search", [{ name: "prefecture", value: "東京" }]));
  chk("都道府県は略称でも引ける", payload.embeds[0].title, "🔎 検索結果 1件");
}
{
  const { payload } = await call(interaction("search", [{ name: "free", value: true }]));
  chk("無料のみ", payload.embeds[0].title, "🔎 検索結果 3件");
  chkTrue("Webリンクにも条件が乗る",
    payload.components[0].components.find((c) => c.style === 5).url.includes("free=1"));
}
{
  const { payload } = await call(interaction("search", [{ name: "keyword", value: "存在しない大会" }]));
  chk("該当なしの件数", payload.embeds[0].title, "🔎 検索結果 0件");
  chkTrue("該当なしでも案内を出す", payload.embeds[0].description.includes("条件に合う大会はありません"));
}
{
  const { payload } = await call(interaction("search", [{ name: "include_past", value: true }]));
  chk("過去も含める", payload.embeds[0].title, "🔎 検索結果 12件");
}

// ページ送り
let nextId = null;
{
  const { payload } = await call(interaction("list", []));
  nextId = payload.components[0].components[1].custom_id;
  chkTrue("custom_id は100文字以内", nextId.length <= 100, `(${nextId.length}文字)`);
}
{
  const body = { type: 3, application_id: "app123", token: "tok123", data: { custom_id: nextId } };
  const { res, payload } = await call(body);
  chk("ボタンは「更新中」を返す", (await res.json()).type, 6);
  chkTrue("2ページ目になる", payload.embeds[0].footer.text.includes("2 / 2 ページ"));
  chk("最終ページでは「次へ」を押せない", payload.components[0].components[1].disabled, true);
  chk("最終ページでは「前へ」を押せる", payload.components[0].components[0].disabled, false);
}
{
  // 長すぎる条件でもクラッシュせず、Webへ誘導する
  const long = "あ".repeat(120);
  const { payload } = await call(interaction("list", [{ name: "period", value: "今月" }]));
  chkTrue("期間指定が条件表示に出る", payload.embeds[0].footer.text.includes("今月"));
  const { payload: p2 } = await call(interaction("search", [{ name: "organizer", value: long }]));
  chk("長い条件でも落ちない", p2.embeds[0].title, "🔎 検索結果 0件");
}

// データ取得に失敗したとき
{
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const href = typeof url === "string" ? url : url.url;
    if (href === DATA_URL) return new Response("boom", { status: 500 });
    return original(url, init);
  };
  const { payload } = await call(interaction("list", []));
  chkTrue("取得に失敗したら理由を返す",
    payload && payload.content && payload.content.includes("うまく取得できませんでした"));
  globalThis.fetch = original;
}

console.log("");
if (failures) {
  console.log(`❌ ${failures}件 失敗しました`);
  process.exit(1);
}
console.log("✅ すべて成功（署名検証・コマンド応答・ページ送り）");
