"""日本語混じりの日時表記をパースするユーティリティ。

Tonamelの表記ゆれ（年省略、和文、範囲指定、ISO、UNIX時刻）を吸収する。
返り値はすべてJST基準の aware datetime。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .config import JST

# 全角→半角
_ZEN = "０１２３４５６７８９／：－〜～"
_HAN = "0123456789/:-~~"
_TRANS = str.maketrans(_ZEN, _HAN)

_WEEKDAY = re.compile(r"[（(][月火水木金土日祝][）)]")
_SPACES = re.compile(r"[　\s]+")

_RANGE_SPLIT = re.compile(r"\s*(?:~|〜|–|—|―|ー|→|から|\bto\b|-{1,2}\s)\s*")

# 2026-09-05 / 2026/9/5 / 2026年9月5日 / 2026.09.05
_YMD = re.compile(r"(?P<y>\d{4})\s*[-/年.]\s*(?P<m>\d{1,2})\s*[-/月.]\s*(?P<d>\d{1,2})\s*日?")
# 9/5 / 9月5日 （年省略）
_MD = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*[-/月]\s*(?P<d>\d{1,2})\s*日?(?!\d)")
_HM = re.compile(r"(?<!\d)(?P<h>\d{1,2})\s*[:時]\s*(?P<mi>\d{1,2})\s*分?(?!\d)")
_H_ONLY = re.compile(r"(?<!\d)(?P<h>\d{1,2})\s*時(?!\d)")


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.translate(_TRANS)
    t = _WEEKDAY.sub(" ", t)
    t = t.replace("開催日時", " ").replace("開催日", " ").replace("日時", " ")
    t = _SPACES.sub(" ", t)
    return t.strip()


def _mk(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime | None:
    try:
        return datetime(y, mo, d, h, mi, tzinfo=JST)
    except ValueError:
        return None


def parse_iso(value: str) -> datetime | None:
    """ISO8601文字列 → JSTのaware datetime。"""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    # "2026-09-05 13:00:00" のような空白区切りも許容
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", s):
        s = s[:10] + "T" + s[11:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # タイムゾーン無しはJSTとみなす（Tonamelは日本のサービス）
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def parse_epoch(value) -> datetime | None:
    """UNIX時刻（秒 or ミリ秒） → JST。"""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n > 1e12:  # ミリ秒
        n /= 1000.0
    # 2000-01-01 〜 2100-01-01 の範囲だけ受け付ける
    if not (946_684_800 <= n <= 4_102_444_800):
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc).astimezone(JST)


def parse_any(value) -> datetime | None:
    """ISO / epoch のどちらでも受け付ける。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return parse_epoch(value)
    if isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"\d{9,13}", s):
            return parse_epoch(s)
        return parse_iso(s)
    return None


def _infer_year(mo: int, d: int, now: datetime) -> int:
    """年が省略された表記の年を推定する。

    「過去2ヶ月〜未来10ヶ月」に収まる年を選ぶ。大会告知は基本的に未来なので、
    今日より前になってしまう場合は翌年とみなす。
    """
    for y in (now.year, now.year + 1, now.year - 1):
        cand = _mk(y, mo, d)
        if cand is None:
            continue
        delta = (cand - now).days
        if -60 <= delta <= 305:
            return y
    return now.year


def parse_datetime_range(
    text: str, now: datetime | None = None
) -> tuple[datetime | None, datetime | None, str | None]:
    """自由記述の日時テキストから (開始, 終了, 日付のみ) を取り出す。

    - 時刻が取れなかった場合、開始はNoneで日付のみ("YYYY-MM-DD")を返す。
    - 終了が取れなければNone。
    """
    now = now or datetime.now(JST)
    t = normalize(text)
    if not t:
        return None, None, None

    parts = [p for p in _RANGE_SPLIT.split(t) if p.strip()]
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else ""

    start = _parse_single(head, now, base=None)
    if start is None:
        # 先頭に日付が無く末尾にある場合（例: "13:00開始 9/5"）に備えて全文で再試行
        start = _parse_single(t, now, base=None)
    if start is None:
        return None, None, None

    end = _parse_single(tail, now, base=start) if tail else None
    if end is not None and end < start:
        # "9/5 22:00〜2:00" のような日跨ぎ
        end = end + timedelta(days=1)

    # 時刻が取れていない（0:00ちょうどで、テキストに時刻表記が無い）なら日付のみ扱い
    has_time = bool(_HM.search(head) or _H_ONLY.search(head))
    if not has_time:
        return None, None, start.strftime("%Y-%m-%d")
    return start, end, start.strftime("%Y-%m-%d")


def _parse_single(
    text: str, now: datetime, base: datetime | None
) -> datetime | None:
    """1つの日時表記をパース。baseがあれば日付省略時にその日付を使う。"""
    if not text:
        return None
    t = text.strip()

    y = mo = d = None
    m = _YMD.search(t)
    if m:
        y, mo, d = int(m["y"]), int(m["m"]), int(m["d"])
    else:
        m = _MD.search(t)
        if m:
            mo, d = int(m["m"]), int(m["d"])
            y = _infer_year(mo, d, now)

    h = mi = None
    hm = _HM.search(t)
    if hm:
        h, mi = int(hm["h"]), int(hm["mi"])
    else:
        ho = _H_ONLY.search(t)
        if ho:
            h, mi = int(ho["h"]), 0

    if mo is None or d is None:
        if base is None:
            return None
        y, mo, d = base.year, base.month, base.day
    if h is None:
        h, mi = 0, 0
    # 24時間超え表記（"25:00"）への対応
    extra_days, h = divmod(h, 24)
    dt = _mk(int(y), int(mo), int(d), int(h), int(mi))
    if dt is None:
        return None
    return dt + timedelta(days=extra_days)


def to_iso(dt: datetime | None) -> str | None:
    return dt.astimezone(JST).isoformat() if dt else None
