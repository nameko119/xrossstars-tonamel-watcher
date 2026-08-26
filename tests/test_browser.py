"""ブラウザ実挙動の確認（ネットには出ない）。

  python -m tests.test_browser

Tonamelの一覧ページを模したローカルHTMLをChromiumで開き、
カード抽出JS（JS_COLLECT_CARDS）が意図通り動くかを確かめる。
Playwright と Chromium が正しく入っているかの確認も兼ねる。
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import JST                                   # noqa: E402
from src.models import Competition                           # noqa: E402
from src.scrape import JS_COLLECT_CARDS, enrich_from_text    # noqa: E402

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=JST)

FAKE_PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>Find Events - Tonamel</title></head><body>
<header><a href="/competitions">大会をさがす</a></header>
<main>
  <ul class="CompetitionList">
    <li class="Card">
      <a href="/competition/abc12">
        <img src="https://example.com/a.png" alt="">
        <p class="title">第3回 クロススターズ杯</p>
      </a>
      <div class="Card__meta">
        <span>2026年9月5日(土) 13:00</span>
        <span>会場: 秋葉原ベルサール</span>
        <span>参加費: 1000円</span>
        <span>定員: 32名</span>
      </div>
    </li>
    <li class="Card">
      <a href="/competition/def34">
        <p class="title">オンライン交流会 vol.9</p>
      </a>
      <div class="Card__meta">
        <span>2026年10月12日(月) 20:00</span>
        <span>オンライン</span>
      </div>
    </li>
  </ul>
  <nav><a href="/competition/abc12">もう一度同じ大会へのリンク</a></nav>
</main></body></html>
"""

failures = []


def check(label, actual, expected):
    if actual == expected:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}\n      期待: {expected!r}\n      実際: {actual!r}")
        failures.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    print("[ブラウザ] Chromiumでカード抽出JSを検証")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "list.html"
        page_path.write_text(FAKE_PAGE, encoding="utf-8")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo").new_page()
            page.goto(page_path.as_uri())
            page.wait_for_selector('a[href*="/competition/"]')
            cards = page.evaluate(JS_COLLECT_CARDS)
            browser.close()

    print(f"  → {len(cards)}件のカードを検出")
    by_id = {c["id"]: c for c in cards}
    check("2件の大会を検出（重複リンクは1件に集約）", sorted(by_id), ["abc12", "def34"])
    check("hrefが絶対URLになる", by_id["abc12"]["href"].endswith("/competition/abc12"), True)
    check("画像を拾う", by_id["abc12"]["img"], "https://example.com/a.png")

    text = by_id["abc12"]["text"]
    check("カードのテキストにタイトルが含まれる", "第3回 クロススターズ杯" in text, True)
    check("カードのテキストに会場が含まれる", "秋葉原ベルサール" in text, True)
    check("隣のカードを巻き込んでいない", "オンライン交流会" in text, False)

    comp = enrich_from_text(Competition(id="abc12", url=by_id["abc12"]["href"]), text, NOW)
    check("日時を抽出", comp.start_at, "2026-09-05T13:00:00+09:00")
    check("会場を抽出", comp.venue, "秋葉原ベルサール")
    check("参加費を抽出", comp.entry_fee, "1000円")
    check("定員を抽出", comp.capacity, "32名")
    check("タイトルを抽出", comp.title, "第3回 クロススターズ杯")

    comp2 = enrich_from_text(Competition(id="def34", url="u"), by_id["def34"]["text"], NOW)
    check("2件目の日時", comp2.start_at, "2026-10-12T20:00:00+09:00")
    check("2件目はオンライン判定", comp2.format, "オンライン")

    print("=" * 60)
    if failures:
        print(f"❌ {len(failures)}件 失敗")
        return 1
    print("✅ すべて成功（Playwright / Chromium も正常）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
