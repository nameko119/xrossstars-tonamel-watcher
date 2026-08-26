"""手元で一覧・検索するためのコマンド。

  python -m src.cli list                        # 今後の大会をすべて表示
  python -m src.cli list --all                  # 終了した大会も含める
  python -m src.cli search 初心者                # キーワード検索
  python -m src.cli search --pref 東京 --free    # 東京 かつ 無料
  python -m src.cli search --period 今週末 --offline
  python -m src.cli search --min-cap 16 --max-fee 1000 --json
"""

from __future__ import annotations

import argparse
import json
import sys

from .normalize import PREFECTURES, normalize_all
from .search import (
    PERIOD_CHOICES, REGION_CHOICES, Query, event_date, period_range, search,
)
from .store import Store

_WD = ["月", "火", "水", "木", "金", "土", "日"]


def _when(comp) -> str:
    from .dateparse import parse_iso

    if comp.start_at:
        dt = parse_iso(comp.start_at)
        if dt:
            return f"{dt:%Y/%m/%d}({_WD[dt.weekday()]}) {dt:%H:%M}"
    d = event_date(comp)
    if d:
        return f"{d:%Y/%m/%d}({_WD[d.weekday()]}) 時刻未定"
    return "日時不明"


def _place(comp) -> str:
    if comp.is_online is True:
        return "オンライン"
    parts = [comp.prefecture or "", comp.venue or ""]
    s = " ".join(p for p in parts if p).strip()
    return s or (comp.format or "—")


def _print_table(hits: list, total: int) -> None:
    if not hits:
        print("該当する大会はありませんでした。")
        return
    print(f"{len(hits)}件を表示（該当 {total}件）\n")
    for c in hits:
        fee = "無料" if c.fee_num == 0 else (f"{c.fee_num:,}円" if c.fee_num else (c.entry_fee or "—"))
        cap = f"{c.capacity_num}人" if c.capacity_num else (c.capacity or "—")
        print(f"■ {c.title or '(タイトル不明)'}")
        print(f"   {_when(c)}   {_place(c)}")
        print(f"   参加費: {fee}   定員: {cap}   主催: {c.organizer or '—'}")
        print(f"   {c.url}")
        print()


def _add_filters(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("keyword", nargs="*", help="大会名・会場・主催者へのキーワード")
    ap.add_argument("--pref", nargs="+", metavar="都道府県",
                    help=f"都道府県で絞る（例: 東京 大阪）")
    ap.add_argument("--region", choices=REGION_CHOICES, help="地方で絞る")
    ap.add_argument("--period", choices=PERIOD_CHOICES, help="期間の近道指定")
    ap.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD")
    ap.add_argument("--online", action="store_true", help="オンラインのみ")
    ap.add_argument("--offline", action="store_true", help="オフラインのみ")
    ap.add_argument("--min-cap", type=int, metavar="N", help="定員がN人以上")
    ap.add_argument("--max-cap", type=int, metavar="N", help="定員がN人以下")
    ap.add_argument("--max-fee", type=int, metavar="円", help="参加費がこの金額以下")
    ap.add_argument("--free", action="store_true", help="無料のみ")
    ap.add_argument("--organizer", metavar="名前", help="主催者名で絞る")
    ap.add_argument("--all", action="store_true", help="終了した大会も含める")
    ap.add_argument("--sort", default="date", choices=["date", "-date", "added", "title"])
    ap.add_argument("--limit", type=int, default=0, help="表示件数（0で全部）")
    ap.add_argument("--json", action="store_true", help="JSONで出力")


def _build_query(args) -> Query:
    q = Query(
        text=" ".join(getattr(args, "keyword", []) or []),
        region=args.region or "",
        prefectures=list(args.pref or []),
        capacity_min=args.min_cap,
        capacity_max=args.max_cap,
        organizer=args.organizer or "",
        include_past=args.all,
        sort=args.sort,
        limit=args.limit,
    )
    if args.online and not args.offline:
        q.online = True
    elif args.offline and not args.online:
        q.online = False
    if args.free:
        q.fee_max = 0
    elif args.max_fee is not None:
        q.fee_max = args.max_fee
    if args.period:
        q.date_from, q.date_to = period_range(args.period)
    if args.date_from:
        q.date_from = args.date_from
    if args.date_to:
        q.date_to = args.date_to
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.cli",
                                 description="収集した大会を一覧・検索する")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add_filters(sub.add_parser("list", help="一覧表示"))
    _add_filters(sub.add_parser("search", help="検索"))
    args = ap.parse_args(argv)

    store = Store()
    if store.is_empty:
        print("大会DBが空です。先に `python -m src.main` を実行してください。")
        return 1
    normalize_all(store.competitions.values())

    all_comps = store.all()
    q = _build_query(args)
    from .search import count as count_hits

    total = count_hits(all_comps, q)
    hits = search(all_comps, q)

    if args.json:
        print(json.dumps([c.to_dict() for c in hits], ensure_ascii=False, indent=2))
    else:
        _print_table(hits, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
