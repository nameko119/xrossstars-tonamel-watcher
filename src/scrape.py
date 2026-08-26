"""Playwrightを使ったTonamelスクレイパー。

TonamelはVue系SPAでHTMLに大会一覧が含まれないため、ヘッドレスChromiumで開く。
セレクタの変更に強くするため、次の3系統から情報を取り、良いものを優先採用する:

  1. ページが裏で叩くAPI(JSON)レスポンスを横取りして再帰的に探索（最も堅い）
  2. JSON-LD (<script type="application/ld+json">) の Event 情報
  3. レンダリング後のDOMテキストからの正規表現抽出（最後の砦）

どれも取れなかった場合は debug/ に画面キャプチャとHTMLを吐くので、
GitHub Actions の Artifacts からダウンロードしてセレクタを調整できる。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Iterable

from playwright.sync_api import sync_playwright, Page, Response, TimeoutError as PWTimeout

from . import config as C
from .dateparse import parse_any, parse_datetime_range, to_iso
from .models import Competition

COMPETITION_ID_RE = re.compile(r"/competition/([A-Za-z0-9][A-Za-z0-9_-]{2,})")

# --- JSONから値を拾うときの候補キー ----------------------------------------
K_TITLE = ("title", "name", "competitionName", "competition_name", "eventName")
K_START = (
    "startAt", "start_at", "startDate", "start_date", "startTime", "start_time",
    "startedAt", "holdAt", "hold_at", "eventStartAt", "competitionStartAt",
    "openAt", "beginAt", "startsAt",
)
K_END = ("endAt", "end_at", "endDate", "end_date", "finishAt", "closeAt", "endsAt")
K_ENTRY_START = ("entryStartAt", "entry_start_at", "recruitStartAt", "applyStartAt")
K_ENTRY_END = ("entryEndAt", "entry_end_at", "recruitEndAt", "applyEndAt", "entryDeadline")
K_VENUE = ("place", "venue", "location", "address", "prefecture", "area", "placeName", "hall")
K_ONLINE = ("isOnline", "online", "is_online", "holdingType", "holding_type", "style", "eventType")
K_ORGANIZER = ("organizer", "owner", "host", "organizerName", "ownerName", "createdBy", "user")
K_FEE = ("entryFee", "entry_fee", "fee", "price", "participationFee")
K_CAPACITY = ("capacity", "maxParticipants", "max_participants", "entryLimit", "participantLimit", "limit")
K_IMAGE = ("imageUrl", "image_url", "image", "thumbnail", "thumbnailUrl", "coverImage", "ogpImage")
K_ID = ("id", "competitionId", "competition_id", "uid", "key", "slug", "hashId")


# ===========================================================================
# JSON探索ヘルパ
# ===========================================================================
def _walk(node: Any) -> Iterable[Any]:
    """入れ子のdict/listを全部たどる。"""
    stack = [node]
    seen = 0
    while stack:
        cur = stack.pop()
        seen += 1
        if seen > 200_000:  # 暴走防止
            return
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    # 大文字小文字・アンダースコアを無視した緩い一致
    lowered = {re.sub(r"[_-]", "", k).lower(): v for k, v in d.items()}
    for k in keys:
        kk = re.sub(r"[_-]", "", k).lower()
        if kk in lowered and lowered[kk] not in (None, "", [], {}):
            return lowered[kk]
    return None


def _as_text(v: Any) -> str:
    """dict/listでも人が読める文字列にする。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        for k in ("name", "title", "displayName", "nickname", "label", "text", "value"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k].strip()
        return ""
    if isinstance(v, list):
        parts = [_as_text(x) for x in v]
        return " / ".join(p for p in parts if p)
    return ""


def index_json_by_id(payloads: list[Any], ids: set[str]) -> dict[str, dict]:
    """横取りしたJSONの中から、大会IDに紐づく辞書を拾い出す。"""
    found: dict[str, dict] = {}
    for payload in payloads:
        for node in _walk(payload):
            if not isinstance(node, dict):
                continue
            raw_id = _first(node, K_ID)
            if not isinstance(raw_id, (str, int)):
                continue
            cid = str(raw_id)
            if cid not in ids:
                continue
            # よりフィールドが充実している方を採用
            score = sum(1 for ks in (K_TITLE, K_START, K_VENUE, K_ORGANIZER, K_FEE)
                        if _first(node, ks) is not None)
            prev = found.get(cid)
            if prev is None or score > prev.get("__score__", -1):
                node = dict(node)
                node["__score__"] = score
                found[cid] = node
    for v in found.values():
        v.pop("__score__", None)
    return found


def competition_from_json(cid: str, d: dict) -> Competition:
    comp = Competition(id=cid, url=C.COMPETITION_URL_TMPL.format(id=cid), source="api")
    comp.title = _as_text(_first(d, K_TITLE))

    start = parse_any(_first(d, K_START))
    end = parse_any(_first(d, K_END))
    if start:
        comp.start_at = to_iso(start)
        comp.start_date = start.strftime("%Y-%m-%d")
    if end:
        comp.end_at = to_iso(end)

    es, ee = parse_any(_first(d, K_ENTRY_START)), parse_any(_first(d, K_ENTRY_END))
    if es or ee:
        comp.entry_period = " 〜 ".join(
            x.strftime("%Y/%m/%d %H:%M") for x in (es, ee) if x
        )

    online = _first(d, K_ONLINE)
    if isinstance(online, bool):
        comp.format = "オンライン" if online else "オフライン"
    else:
        ot = _as_text(online)
        if ot:
            low = ot.lower()
            if "online" in low or "オンライン" in ot:
                comp.format = "オンライン"
            elif "offline" in low or "オフライン" in ot or "realtime" in low:
                comp.format = "オフライン"

    comp.venue = _as_text(_first(d, K_VENUE))
    comp.organizer = _as_text(_first(d, K_ORGANIZER))
    fee = _first(d, K_FEE)
    comp.entry_fee = _as_text(fee) if not isinstance(fee, (int, float)) else f"{int(fee)}円"
    cap = _first(d, K_CAPACITY)
    comp.capacity = _as_text(cap) if not isinstance(cap, (int, float)) else f"{int(cap)}人"
    comp.image_url = _as_text(_first(d, K_IMAGE))
    # 生JSONは肥大化しやすいので、素性の分かるキーだけ残す
    comp.raw_json = {
        k: v for k, v in d.items()
        if isinstance(v, (str, int, float, bool)) and len(str(v)) < 400
    }
    return comp


# ===========================================================================
# DOM / テキストからの抽出
# ===========================================================================
# ラベル → 値 を拾うための定義。
# カード内が <span> の羅列だと innerText が1行に潰れることがあるため、
# 「次のラベルが始まる直前」でも値を打ち切れるようにしている。
_LABELS = {
    "entry_fee": ("参加費用", "参加費", "エントリー費", "費用"),
    "capacity": ("定員", "募集人数", "参加人数", "最大人数", "上限"),
    "organizer": ("主催者", "主催", "オーガナイザー", "開催者"),
    "venue": ("会場", "開催場所", "開催地", "場所"),
    "entry_period": ("エントリー期間", "受付期間", "応募期間", "募集期間"),
}
_ALL_LABELS = sorted(
    {w for words in _LABELS.values() for w in words}, key=len, reverse=True
)
_STOP = r"(?=\s*(?:" + "|".join(_ALL_LABELS) + r")\s*[:：]|\n|$)"
_LABEL_PATTERNS = {
    field: r"(?:" + "|".join(words) + r")\s*[:：]?\s*(.{1,80}?)" + _STOP
    for field, words in _LABELS.items()
}
# 「開催場所」欄のブロックを取り出すための正規表現。
# Tonamelの詳細ページは、ページのかなり下のほうに
#     開催場所
#     カードショップおうち秋葉原店      ← 会場名
#     東京都千代田区外神田4-7-1 ...     ← 住所
#     連絡先
# という並びで出る。raw_text は途中で切ってしまうので、
# ここで住所だけ拾って別フィールドに保存しておく。
_VENUE_BLOCK = re.compile(
    r"(?:開催場所|開催地|会場|住所|所在地)\s*[:：]?\s*\n?((?:.+\n?){0,4})"
)
# 住所らしい行かどうかの判定（数字・丁目・区市町村・郵便番号のどれかを含む）
_ADDRESS_LIKE = re.compile(
    r"〒|\d|丁目|番地|[都道府県][^\s]{0,12}[市区郡町村]|[市区郡町村]"
)
# 明らかに住所ではない行（次の項目の見出しなど）
_NOT_ADDRESS = re.compile(
    r"^(?:連絡先|お問い合わせ|主催|参加費|定員|備考|イベント詳細|続きを読む|"
    r"開催形式|エントリー|タイムスケジュール|アクセス)"
)

_DATE_LINE = re.compile(
    r"(?:\d{4}\s*[-/年.]\s*)?\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?"
    r"(?:\s*[（(][月火水木金土日祝][）)])?"
    r"(?:[^\n]{0,30}?\d{1,2}\s*[:時]\s*\d{2})?"
)


def extract_address(text: str, venue: str = "") -> str:
    """「開催場所」欄から住所の行を取り出す。

    会場名の次に来る、住所らしい行を最大2行ぶん拾う。
    見つからなければ空文字を返す（推測はしない）。
    """
    if not text:
        return ""
    for m in _VENUE_BLOCK.finditer(text):
        lines = [l.strip() for l in m.group(1).splitlines()]
        lines = [l for l in lines if l]
        picked: list[str] = []
        for line in lines:
            if _NOT_ADDRESS.match(line):
                break
            if venue and line.replace(" ", "") == venue.replace(" ", ""):
                continue          # 1行目の会場名そのものは住所ではない
            if venue and line.rstrip(" 　様") == venue.rstrip(" 　様"):
                continue
            if not _ADDRESS_LIKE.search(line):
                continue
            picked.append(line)
            if len(picked) >= 2:
                break
        if picked:
            return " ".join(picked)[:160]
    # 「開催場所」欄が無くても、郵便番号があればその行を住所とみなす
    m = re.search(r"〒\s*\d{3}[-−]?\d{4}[^\n]{0,80}", text)
    if m:
        return m.group(0).strip()[:160]
    # 一覧ページのカードのように、住所がラベル無しで1行だけ載っている場合
    # （例: "愛知県名古屋市中村区椿町13-4スパーク椿町6F"）
    from .normalize import ADDRESS_SHAPE

    m = ADDRESS_SHAPE.search(text)
    if m:
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        return line.strip()[:160]
    return ""


def enrich_from_text(comp: Competition, text: str, now: datetime) -> Competition:
    """画面テキストから拾える情報を補完する（既にある値は壊さない）。"""
    if not text:
        return comp
    # raw_text は保存サイズを抑えるため途中で切る。
    # 住所など「あとで必ず使うもの」は、切る前にここで取り出しておくこと。
    comp.raw_text = text[:1500]

    if not comp.start_at and not comp.start_date:
        m = _DATE_LINE.search(text)
        if m:
            # 日付らしき部分の周辺（時刻や範囲を巻き込む）を渡す
            window = text[m.start(): m.start() + 60]
            s, e, d = parse_datetime_range(window, now=now)
            if s:
                comp.start_at = to_iso(s)
                comp.start_date = s.strftime("%Y-%m-%d")
                if e:
                    comp.end_at = to_iso(e)
            elif d:
                comp.start_date = d

    for field_name, pat in _LABEL_PATTERNS.items():
        if getattr(comp, field_name):
            continue
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip(" 　:：-−–—")
            if val and len(val) >= 1:
                setattr(comp, field_name, val[:120])

    if not comp.address:
        comp.address = extract_address(text, comp.venue)

    if not comp.format:
        if "オンライン" in text:
            comp.format = "オンライン"
        elif "オフライン" in text or comp.venue:
            comp.format = "オフライン"

    if not comp.title:
        for line in (l.strip() for l in text.splitlines()):
            if len(line) >= 3 and not _DATE_LINE.fullmatch(line):
                comp.title = line[:150]
                break
    return comp


# ページ内で実行するJS：大会カードを拾う
JS_COLLECT_CARDS = r"""
() => {
  const out = {};
  const anchors = Array.from(document.querySelectorAll('a[href*="/competition/"]'));
  for (const a of anchors) {
    const m = (a.getAttribute('href') || '').match(/\/competition\/([A-Za-z0-9][A-Za-z0-9_-]{2,})/);
    if (!m) continue;
    const id = m[1];
    // カードらしい祖先までさかのぼる（テキスト量が増える範囲で最大4段）
    let node = a, best = a, bestLen = (a.innerText || '').length;
    for (let i = 0; i < 4 && node.parentElement; i++) {
      node = node.parentElement;
      const t = (node.innerText || '');
      const links = node.querySelectorAll('a[href*="/competition/"]').length;
      if (links > 1) break;               // 他の大会を巻き込み始めたら停止
      if (t.length > bestLen) { best = node; bestLen = t.length; }
    }
    const img = best.querySelector('img');
    const prev = out[id];
    const text = (best.innerText || '').trim();
    if (!prev || text.length > prev.text.length) {
      out[id] = {
        id,
        href: new URL(a.getAttribute('href'), location.origin).toString(),
        text,
        title: (a.getAttribute('title') || a.getAttribute('aria-label') || '').trim(),
        img: img ? (img.currentSrc || img.src || '') : '',
      };
    }
  }
  return Object.values(out);
}
"""

JS_JSONLD = r"""
() => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
        .map(s => s.textContent || '')
"""

JS_PAGE_TEXT = "() => document.body ? document.body.innerText : ''"


# ===========================================================================
# ブラウザ操作
# ===========================================================================
class JsonCollector:
    """裏で走るAPI通信のJSONを溜め込む。"""

    def __init__(self) -> None:
        self.payloads: list[Any] = []
        self.urls: list[str] = []

    def handle(self, response: Response) -> None:
        try:
            url = response.url
            if url.startswith("data:"):
                return
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            if response.status >= 400:
                return
            body = response.json()
        except Exception:
            return
        self.urls.append(url)
        self.payloads.append(body)


def _dismiss_overlays(page: Page) -> None:
    """Cookie同意などのオーバーレイを可能な範囲で閉じる。"""
    labels = ["同意", "許可", "OK", "閉じる", "Accept", "Agree", "Got it"]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=re.compile(label)).first
            if btn.is_visible(timeout=500):
                btn.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _load_all(page: Page) -> None:
    """無限スクロール・「もっと見る」を可能な限り展開する。"""
    more_re = re.compile(r"もっと見る|さらに(?:表示|読み込)|次の\d*件|Load more|See more|More")
    last_count = -1
    for _ in range(C.MAX_SCROLL_ROUNDS):
        try:
            count = page.locator('a[href*="/competition/"]').count()
        except Exception:
            break
        if count == last_count:
            # 変化が無ければ「もっと見る」を探す
            clicked = False
            try:
                btn = page.get_by_role("button", name=more_re).first
                if btn.is_visible(timeout=800):
                    btn.click(timeout=2000)
                    clicked = True
            except Exception:
                pass
            if not clicked:
                break
        last_count = count
        try:
            page.mouse.wheel(0, 4000)
        except Exception:
            pass
        page.wait_for_timeout(1200)


def _save_debug(page: Page, collector: JsonCollector, tag: str) -> None:
    C.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(C.DEBUG_DIR / f"{tag}.png"), full_page=True)
    except Exception:
        pass
    try:
        (C.DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        (C.DEBUG_DIR / f"{tag}_api_urls.txt").write_text(
            "\n".join(collector.urls), encoding="utf-8"
        )
        sample = json.dumps(collector.payloads[:20], ensure_ascii=False, indent=2)
        (C.DEBUG_DIR / f"{tag}_api_payloads.json").write_text(
            sample[:2_000_000], encoding="utf-8"
        )
    except Exception:
        pass


def _parse_jsonld(page: Page) -> list[Any]:
    out: list[Any] = []
    try:
        for raw in page.evaluate(JS_JSONLD) or []:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _enrich_from_jsonld(comp: Competition, blobs: list[Any], now: datetime) -> Competition:
    for blob in blobs:
        for node in _walk(blob):
            if not isinstance(node, dict):
                continue
            if "startDate" not in node and "startdate" not in {k.lower() for k in node}:
                continue
            s = parse_any(_first(node, ("startDate", "startdate")))
            e = parse_any(_first(node, ("endDate", "enddate")))
            if s and not comp.start_at:
                comp.start_at = to_iso(s)
                comp.start_date = s.strftime("%Y-%m-%d")
            if e and not comp.end_at:
                comp.end_at = to_iso(e)
            if not comp.title:
                comp.title = _as_text(_first(node, K_TITLE))
            if not comp.venue:
                loc = node.get("location")
                comp.venue = _as_text(loc)
            if not comp.organizer:
                comp.organizer = _as_text(node.get("organizer"))
    return comp


def _needs_detail(comp: Competition, known_ids: set[str],
                  known: dict[str, Competition] | None = None) -> bool:
    """詳細ページを開く価値があるか。既知かつ情報が揃っていれば開かない。"""
    if comp.id not in known_ids:
        return True
    if not (comp.start_at or comp.start_date):
        return True
    if not comp.title:
        return True
    # 抽出ロジックを直したときは、既存の大会も1回だけ取り直す
    prev = (known or {}).get(comp.id)
    if prev is not None and (prev.detail_version or 0) < C.DETAIL_VERSION:
        return True
    # 前回の実行で取得上限に当たって詳細が取れなかったもの
    if prev is not None and prev.source != "detail":
        return True
    return False


def scrape(fetch_detail: bool | None = None, detail_ids: set[str] | None = None,
           known: dict[str, Competition] | None = None) -> tuple[list[Competition], dict]:
    """一覧（＋必要なら詳細）を取得する。

    Args:
        fetch_detail: 詳細ページも開くか。Noneならconfigに従う。
        detail_ids: 詳細を取りにいくIDの集合。Noneなら全件（上限あり）。
        known: DBに既にある大会。渡すと「新規＋情報不足＋要再取得」だけ詳細を開く。

    Returns:
        (大会リスト, 実行メタ情報)
    """
    if fetch_detail is None:
        fetch_detail = C.FETCH_DETAIL
    now = datetime.now(C.JST)
    meta: dict[str, Any] = {"list_url": C.LIST_URL, "errors": [], "api_hit": 0}
    results: dict[str, Competition] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            user_agent=C.USER_AGENT,
            viewport={"width": 1440, "height": 2200},
            extra_http_headers={"Accept-Language": "ja,en-US;q=0.8,en;q=0.6"},
        )
        page = context.new_page()
        collector = JsonCollector()
        page.on("response", collector.handle)

        # ---- 一覧ページ -----------------------------------------------------
        try:
            page.goto(C.LIST_URL, wait_until="domcontentloaded", timeout=C.LIST_TIMEOUT_MS)
        except PWTimeout:
            meta["errors"].append("一覧ページの読み込みがタイムアウトしました")
        _dismiss_overlays(page)
        try:
            page.wait_for_selector('a[href*="/competition/"]', timeout=C.LIST_TIMEOUT_MS)
        except PWTimeout:
            meta["errors"].append("大会カードが描画されませんでした（セレクタ要確認）")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        _load_all(page)

        cards = []
        try:
            cards = page.evaluate(JS_COLLECT_CARDS) or []
        except Exception as e:  # pragma: no cover
            meta["errors"].append(f"カード抽出に失敗: {e}")

        ids = {c["id"] for c in cards if c.get("id")}
        meta["list_ids"] = sorted(ids)
        meta["list_count"] = len(ids)

        api_index = index_json_by_id(collector.payloads, ids)
        meta["api_hit"] = len(api_index)
        meta["api_urls"] = collector.urls[-40:]

        for card in cards:
            cid = card["id"]
            if cid in api_index:
                comp = competition_from_json(cid, api_index[cid])
            else:
                comp = Competition(id=cid, url=card.get("href") or C.COMPETITION_URL_TMPL.format(id=cid))
            if card.get("title") and not comp.title:
                comp.title = card["title"]
            if card.get("img") and not comp.image_url:
                comp.image_url = card["img"]
            comp = enrich_from_text(comp, card.get("text", ""), now)
            results[cid] = comp

        if C.DEBUG or not ids:
            _save_debug(page, collector, "list")

        # ---- 詳細ページ -----------------------------------------------------
        if fetch_detail and results:
            if detail_ids is not None:
                targets = [cid for cid in results if cid in detail_ids]
            elif known is not None:
                known_ids = set(known)
                targets = [cid for cid, c in results.items()
                           if _needs_detail(c, known_ids, known)]
            else:
                targets = list(results)
            targets = targets[: C.MAX_DETAIL_FETCH]
            meta["detail_targets"] = len(targets)
            meta["detail_fetched"] = []
            for cid in targets:
                try:
                    detail = _scrape_detail(context, cid, now, meta)
                except Exception as e:  # pragma: no cover
                    meta["errors"].append(f"詳細取得失敗 {cid}: {e}")
                    continue
                if detail:
                    results[cid] = results[cid].merge_from(detail)
                    meta["detail_fetched"].append(cid)
                time.sleep(C.DETAIL_SLEEP_SEC)

        context.close()
        browser.close()

    for comp in results.values():
        comp.last_updated = now.isoformat()
    return list(results.values()), meta


def _scrape_detail(context, cid: str, now: datetime, meta: dict) -> Competition | None:
    url = C.COMPETITION_URL_TMPL.format(id=cid)
    page = context.new_page()
    collector = JsonCollector()
    page.on("response", collector.handle)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=C.DETAIL_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1200)

        api_index = index_json_by_id(collector.payloads, {cid})
        if api_index:
            comp = competition_from_json(cid, api_index[cid])
        else:
            comp = Competition(id=cid, url=url, source="detail")
        comp.source = "detail"

        comp = _enrich_from_jsonld(comp, _parse_jsonld(page), now)

        try:
            text = page.evaluate(JS_PAGE_TEXT) or ""
        except Exception:
            text = ""
        comp = enrich_from_text(comp, text, now)

        if not comp.title:
            try:
                comp.title = (page.title() or "").replace(" | Tonamel", "").strip()
            except Exception:
                pass
        comp.detail_version = C.DETAIL_VERSION

        if C.DEBUG:
            _save_debug(page, collector, f"detail_{cid}")
        return comp
    finally:
        page.close()
