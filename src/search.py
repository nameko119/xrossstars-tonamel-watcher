"""大会の一覧・検索ロジック。

Webページ（docs/index.html）とDiscord botのどちらからも同じ条件で
絞り込めるように、判定はすべてここに集約している。
JS側（bot / Webページ）には同じ規則を移植してあり、
tests/test_search_parity.js で結果が一致することを確認している。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config as C
from .dateparse import parse_iso
from .models import Competition
from .normalize import PREF_TO_REGION, SHORT_TO_PREF


def fold(text: str) -> str:
    """比較用に文字列をならす（全角/半角・大文字小文字・空白の違いを吸収）。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Query:
    """検索条件。すべて省略可能で、指定されたものだけを条件にする。"""

    text: str = ""                       # 大会名・会場・主催者へのキーワード
    date_from: str = ""                  # "YYYY-MM-DD" この日以降
    date_to: str = ""                    # "YYYY-MM-DD" この日以前
    prefectures: list[str] = field(default_factory=list)  # 例: ["東京都"]
    region: str = ""                     # 例: "関東"
    online: bool | None = None           # True=オンラインのみ / False=オフラインのみ
    capacity_min: int | None = None
    capacity_max: int | None = None
    fee_max: int | None = None           # この金額以下（0で無料のみ）
    organizer: str = ""
    include_past: bool = False           # 終了した大会も含めるか
    include_undated: bool = True         # 日付不明の大会を含めるか
    sort: str = "date"                   # date / -date / added / title
    limit: int = 0                       # 0で無制限
    offset: int = 0


# ---------------------------------------------------------------- 補助
def event_date(comp: Competition) -> date | None:
    if comp.start_at:
        dt = parse_iso(comp.start_at)
        if dt:
            return dt.date()
    if comp.start_date:
        try:
            return datetime.strptime(comp.start_date, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def searchable_text(comp: Competition) -> str:
    return fold(" ".join([
        comp.title, comp.venue, comp.address, comp.organizer, comp.prefecture,
        comp.region, comp.format, comp.id,
    ]))


def resolve_prefecture(name: str) -> str:
    """「東京」「とうきょう」ではなく「東京」→「東京都」のように正式名へ寄せる。"""
    n = fold(name).replace(" ", "")
    for short, pref in SHORT_TO_PREF.items():
        if fold(short) == n:
            return pref
    return name


# ---------------------------------------------------------------- 本体
def matches(comp: Competition, q: Query, today: date | None = None) -> bool:
    today = today or datetime.now(C.JST).date()
    d = event_date(comp)

    # 日付まわり
    if d is None:
        if not q.include_undated:
            return False
        # 日付が分からないものは、期間指定があるときは対象外にする
        if q.date_from or q.date_to:
            return False
    else:
        if not q.include_past and d < today:
            return False
        if q.date_from and d < _to_date(q.date_from, date.min):
            return False
        if q.date_to and d > _to_date(q.date_to, date.max):
            return False

    # 開催形式
    if q.online is not None and comp.is_online is not q.online:
        return False

    # 地域
    if q.prefectures:
        wanted = {resolve_prefecture(p) for p in q.prefectures}
        if comp.prefecture not in wanted:
            return False
    if q.region and comp.region != q.region:
        return False

    # 定員
    if q.capacity_min is not None:
        if comp.capacity_num is None or comp.capacity_num < q.capacity_min:
            return False
    if q.capacity_max is not None:
        if comp.capacity_num is None or comp.capacity_num > q.capacity_max:
            return False

    # 参加費
    if q.fee_max is not None:
        if comp.fee_num is None or comp.fee_num > q.fee_max:
            return False

    # 主催者
    if q.organizer and fold(q.organizer) not in fold(comp.organizer):
        return False

    # キーワード（空白区切りのAND検索）
    if q.text:
        haystack = searchable_text(comp)
        for word in fold(q.text).split(" "):
            if word and word not in haystack:
                return False

    return True


def _to_date(value: str, fallback: date) -> date:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return fallback


def sort_key(comp: Competition, mode: str):
    d = event_date(comp)
    far = date.max if mode != "-date" else date.min
    if mode == "title":
        return (fold(comp.title), comp.id)
    if mode == "added":
        return (comp.first_seen or "", comp.id)
    return (d or far, comp.id)


def search(competitions: list[Competition], q: Query,
           today: date | None = None) -> list[Competition]:
    hits = [c for c in competitions if matches(c, q, today)]
    hits.sort(key=lambda c: sort_key(c, q.sort), reverse=(q.sort == "-date"))
    if q.offset:
        hits = hits[q.offset:]
    if q.limit:
        hits = hits[: q.limit]
    return hits


def count(competitions: list[Competition], q: Query, today: date | None = None) -> int:
    """limit/offsetを無視した該当件数。"""
    return sum(1 for c in competitions if matches(c, q, today))


# ---------------------------------------------------------------- 便利な期間指定
def period_range(name: str, today: date | None = None) -> tuple[str, str]:
    """「今週末」「今月」などを (date_from, date_to) に変換する。"""
    today = today or datetime.now(C.JST).date()
    name = (name or "").strip()

    if name in ("今日", "today"):
        return today.isoformat(), today.isoformat()
    if name in ("明日", "tomorrow"):
        d = today + timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if name in ("今週末", "weekend", "週末"):
        # 今日以降の直近の土曜〜日曜
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        return sat.isoformat(), (sat + timedelta(days=1)).isoformat()
    if name in ("今週", "week"):
        mon = today - timedelta(days=today.weekday())
        return max(mon, today).isoformat(), (mon + timedelta(days=6)).isoformat()
    if name in ("来週", "next_week"):
        mon = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return mon.isoformat(), (mon + timedelta(days=6)).isoformat()
    if name in ("今月", "month"):
        first = today.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return max(first, today).isoformat(), (nxt - timedelta(days=1)).isoformat()
    if name in ("来月", "next_month"):
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
    if name in ("30日以内", "30days"):
        return today.isoformat(), (today + timedelta(days=30)).isoformat()
    return "", ""


PERIOD_CHOICES = ["今日", "明日", "今週末", "今週", "来週", "今月", "来月", "30日以内"]
REGION_CHOICES = list(dict.fromkeys(PREF_TO_REGION.values()))
