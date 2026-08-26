"""エントリーポイント。

  python -m src.main                 # 通常実行（取得→差分検知→通知→ICS生成）
  python -m src.main --dry-run       # 通知もファイル書き込みもせず結果だけ表示
  python -m src.main --no-detail     # 一覧ページだけ取得（高速・お試し向け）
  python -m src.main --debug         # debug/ に画面キャプチャとAPIログを出す
  python -m src.main --fixture x.json  # ネットに出ずJSONから読み込んで動作確認
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import build_ics, build_site, config as C
from .models import Competition
from .normalize import normalize_all
from .notify_discord import diff_note, format_when, notify
from .quiet import in_quiet_hours, is_enabled as quiet_enabled, window_label
from .store import Store


def _print_summary(diff, store: Store, meta: dict, ics_count: int | None) -> None:
    print("=" * 60)
    print(f"実行日時      : {datetime.now(C.JST).strftime('%Y-%m-%d %H:%M:%S')} JST")
    print(f"一覧取得件数  : {meta.get('list_count', 0)}")
    print(f"API由来の件数 : {meta.get('api_hit', 0)}")
    if "detail_fetched" in meta:
        print(f"詳細取得件数  : {len(meta['detail_fetched'])}")
    print(f"新規          : {len(diff.new)}{'（初回シード）' if diff.is_seed else ''}")
    print(f"変更          : {len(diff.changed)}")
    print(f"変化なし      : {diff.unchanged}")
    print(f"DB総件数      : {len(store.competitions)}")
    if ics_count is not None:
        print(f"ICSイベント数 : {ics_count}")
    if quiet_enabled():
        seed, n_new, n_changed = store.pending_counts()
        held = n_new + n_changed + (1 if seed is not None else 0)
        print(f"静音時間帯    : {window_label()}"
              + ("（いま静音中）" if in_quiet_hours() else "")
              + (f" / 保留中 {held}件" if held else ""))
    for err in meta.get("errors", []):
        print(f"⚠️  {err}")
    print("=" * 60)
    for comp in diff.new[:30]:
        print(f"  🆕 {format_when(comp):<28} {comp.title or '(タイトル不明)'}  {comp.url}")
    for old, new in diff.changed[:30]:
        print(f"  ✏️  {format_when(new):<28} {new.title or new.id}  {new.url}")


def _load_fixture(path: Path) -> tuple[list[Competition], dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["competitions"] if isinstance(raw, dict) and "competitions" in raw else raw
    if isinstance(items, dict):
        items = list(items.values())
    comps = [Competition.from_dict(d) for d in items]
    return comps, {"list_count": len(comps), "api_hit": 0, "errors": [], "fixture": str(path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tonamel上のXrossstars大会を監視する")
    ap.add_argument("--dry-run", action="store_true", help="通知・保存をせず結果表示のみ")
    ap.add_argument("--no-detail", action="store_true", help="詳細ページを開かない")
    ap.add_argument("--debug", action="store_true", help="debug/ にキャプチャとAPIログを保存")
    ap.add_argument("--fixture", type=Path, help="ネットに出ずJSONから読み込む（動作確認用）")
    ap.add_argument("--no-discord", action="store_true", help="Discord通知だけ止める")
    ap.add_argument("--ignore-quiet", action="store_true",
                    help="静音時間帯でも保留せずすぐ通知する（手動実行・動作確認向け）")
    args = ap.parse_args(argv)

    if args.debug:
        C.DEBUG = True

    store = Store()

    if args.fixture:
        scraped, meta = _load_fixture(args.fixture)
    else:
        from .scrape import scrape  # Playwrightの読み込みを遅らせる

        scraped, meta = scrape(
            fetch_detail=not args.no_detail,
            known=store.competitions,
        )

    if not scraped:
        print("❌ 大会を1件も取得できませんでした。")
        print("   debug/ の list.png / list.html / list_api_urls.txt を確認してください。")
        print("   （ページ構造が変わった場合は src/scrape.py のセレクタ調整が必要です）")
        for err in meta.get("errors", []):
            print(f"   ⚠️  {err}")
        # DBとICSは壊さずそのまま残して異常終了させる
        return 2

    diff = store.apply(scraped)
    # 検索用の項目（都道府県・定員の人数・参加費の金額・オンライン判定）を
    # 毎回すべての大会に付け直す。判定ルールを直したとき、過去分にも遡って効く。
    normalize_all(store.competitions.values())

    ics_count = None
    notify_info: dict = {"mode": "dry-run"}
    if args.dry_run:
        ics_count = build_ics.build(store.all()).count("BEGIN:VEVENT")
        print("（--dry-run のため保存も通知もしていません）")
        if quiet_enabled():
            state = "静音時間帯です" if in_quiet_hours() else "静音時間帯ではありません"
            print(f"（静音時間帯: {window_label()} / いまは{state}）")
    else:
        ics_count = build_ics.write(store.all())
        build_site.write(store.all())   # docs/index.html（一覧・検索ページ）
        # 通知の可否で保留リストが変わるので、保存より先に通知処理を行う
        notify_info = _handle_notifications(store, diff, args)
        store.save(run_meta={
            "list_count": meta.get("list_count"),
            "api_hit": meta.get("api_hit"),
            "new": len(diff.new),
            "changed": len(diff.changed),
            "notify": notify_info,
            "errors": meta.get("errors", []),
        })

    _print_summary(diff, store, meta, ics_count)

    # GitHub Actionsのサマリ欄に出す
    _write_gh_summary(diff, store, meta, ics_count)
    return 0


def _handle_notifications(store: Store, diff, args) -> dict:
    """通知を送る／静音時間帯なら保留する。"""
    if args.no_discord:
        print("[discord] --no-discord のため通知しません")
        return {"mode": "skipped"}

    new_ids = [c.id for c in diff.new]
    changed_pairs = [(new, diff_note(old, new)) for old, new in diff.changed]
    if not C.NOTIFY_ON_CHANGE:
        changed_pairs = []

    # ---- 静音時間帯：送らずに積んでおく --------------------------------
    if in_quiet_hours() and not args.ignore_quiet:
        if diff.is_seed:
            # 初回は件数だけ覚えておく。個別に積むと朝に全件が新着通知として飛んでしまう
            store.defer([], [], seed_count=len(diff.new))
        elif diff.has_updates:
            store.defer(new_ids, [(c.id, note) for c, note in changed_pairs])
        seed, n_new, n_changed = store.pending_counts()
        held = []
        if seed is not None:
            held.append(f"初期登録{seed}件")
        if n_new:
            held.append(f"新着{n_new}件")
        if n_changed:
            held.append(f"変更{n_changed}件")
        print(
            f"[discord] 静音時間帯（{window_label()}）のため通知しません。"
            + (f"保留中: {' / '.join(held)}" if held else "保留中の通知はありません")
        )
        return {"mode": "deferred", "pending": {"seed": seed, "new": n_new, "changed": n_changed}}

    # ---- 静音時間外：まず夜のあいだに溜まった分を送る --------------------
    sent = 0
    delivered_pending = False
    if store.has_pending:
        p_seed, p_new, p_changed = store.peek_pending()
        ok, unconfigured = True, False
        if p_seed is not None:
            res = notify([], seed_count=p_seed)
            ok &= res["sent"] > 0
            unconfigured |= bool(res.get("skipped_reason"))
        if p_new or p_changed:
            res = notify(p_new, p_changed, deferred=True)
            ok &= res["sent"] > 0
            sent += res["sent"]
            unconfigured |= bool(res.get("skipped_reason"))
        if ok:
            store.clear_pending()
            delivered_pending = True
            print("[discord] 夜間に保留していた通知を送信しました")
        elif unconfigured:
            print("[discord] Webhookが未設定のため、保留分はそのまま残しておきます")
        else:
            print("[discord] 保留分の送信に失敗したため、次回に持ち越します")

    # ---- 今回の分 --------------------------------------------------------
    if diff.is_seed:
        sent += notify([], seed_count=len(diff.new), seed_samples=diff.new)["sent"]
    elif diff.has_updates:
        sent += notify(diff.new, changed_pairs)["sent"]
    elif not delivered_pending:
        print("[discord] 新着・変更なしのため通知しません")

    return {"mode": "sent", "sent": sent, "delivered_pending": delivered_pending}


def _write_gh_summary(diff, store, meta, ics_count) -> None:
    import os

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Xrossstars 大会ウォッチャー",
        "",
        f"- 一覧取得: **{meta.get('list_count', 0)}件** / API由来: {meta.get('api_hit', 0)}件",
        f"- 新規: **{len(diff.new)}件**{'（初回シード）' if diff.is_seed else ''}",
        f"- 変更: **{len(diff.changed)}件**",
        f"- DB総件数: {len(store.competitions)} / ICSイベント: {ics_count}",
    ]
    if quiet_enabled():
        seed, n_new, n_changed = store.pending_counts()
        held = n_new + n_changed + (1 if seed is not None else 0)
        if in_quiet_hours():
            lines.append(f"- 🌙 静音時間帯（{window_label()}）のため通知は保留中（{held}件）")
        elif held:
            lines.append(f"- 保留中の通知: {held}件")
    for err in meta.get("errors", []):
        lines.append(f"- ⚠️ {err}")
    if diff.new:
        lines += ["", "### 新着", "", "| 日時 | 大会名 | リンク |", "|---|---|---|"]
        for c in diff.new[:25]:
            lines.append(f"| {format_when(c)} | {(c.title or c.id)} | [開く]({c.url}) |")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
