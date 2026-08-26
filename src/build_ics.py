"""大会DBから iCalendar (.ics) を生成する。

Googleカレンダーの「URLで追加」で購読する前提。
実行のたびに中身が揺れると git の差分が汚れるので、
出力はソート済み・タイムスタンプ固定（first_seen基準）にして安定させている。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config as C
from .dateparse import parse_iso
from .models import Competition

PRODID = "-//xrossstars-tonamel-watcher//JP"


def _esc(text: str) -> str:
    """RFC5545のテキストエスケープ。"""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> list[str]:
    """1行75オクテット以内に折り返す（UTF-8の途中で切らない）。"""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    out: list[str] = []
    buf = b""
    limit = 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(buf) + len(b) > limit:
            out.append(buf.decode("utf-8"))
            buf = b
            limit = 74  # 継続行は先頭の空白1文字ぶん狭くする
        else:
            buf += b
    if buf:
        out.append(buf.decode("utf-8"))
    return [out[0]] + [" " + s for s in out[1:]]


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _describe(comp: Competition) -> str:
    lines = []
    if comp.format or comp.venue:
        place = " / ".join(x for x in (comp.format, comp.venue) if x)
        lines.append(f"会場: {place}")
    if comp.organizer:
        lines.append(f"主催: {comp.organizer}")
    if comp.entry_fee:
        lines.append(f"参加費: {comp.entry_fee}")
    if comp.capacity:
        lines.append(f"定員: {comp.capacity}")
    if comp.entry_period:
        lines.append(f"エントリー期間: {comp.entry_period}")
    lines.append("")
    lines.append(comp.url)
    return "\n".join(lines)


def _event_lines(comp: Competition, dtstamp: str) -> list[str] | None:
    start = parse_iso(comp.start_at) if comp.start_at else None
    lines = [
        "BEGIN:VEVENT",
        f"UID:tonamel-{comp.id}@xrossstars-watcher",
        f"DTSTAMP:{dtstamp}",
        f"SEQUENCE:{int(comp.seq or 0)}",
    ]

    if start:
        end = parse_iso(comp.end_at) if comp.end_at else None
        if end is None or end <= start:
            end = start + timedelta(hours=C.DEFAULT_DURATION_HOURS)
        lines.append(f"DTSTART:{_utc(start)}")
        lines.append(f"DTEND:{_utc(end)}")
    elif comp.start_date:
        try:
            d = datetime.strptime(comp.start_date, "%Y-%m-%d").date()
        except ValueError:
            return None
        lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        return None  # 日付が全く不明なものはカレンダーに載せない

    title = comp.title or f"Xrossstars大会 {comp.id}"
    prefix = "🟦" if comp.format == "オンライン" else ""
    lines.append(f"SUMMARY:{_esc((prefix + ' ' if prefix else '') + title)}")
    lines.append(f"DESCRIPTION:{_esc(_describe(comp))}")
    lines.append(f"URL:{comp.url}")
    loc = comp.venue or comp.format
    if loc:
        lines.append(f"LOCATION:{_esc(loc)}")
    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:TRANSPARENT")
    lines.append("END:VEVENT")
    return lines


def _reference_date(comp: Competition) -> datetime | None:
    if comp.start_at:
        return parse_iso(comp.start_at)
    if comp.start_date:
        try:
            return datetime.strptime(comp.start_date, "%Y-%m-%d").replace(tzinfo=C.JST)
        except ValueError:
            return None
    return None


def build(competitions: list[Competition], now: datetime | None = None) -> str:
    now = now or datetime.now(C.JST)
    body: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(C.CALENDAR_NAME)}",
        f"X-WR-CALDESC:{_esc(C.CALENDAR_DESC)}",
        "X-WR-TIMEZONE:Asia/Tokyo",
        "REFRESH-INTERVAL;VALUE=DURATION:PT3H",
        "X-PUBLISHED-TTL:PT3H",
    ]

    cutoff = None
    if C.ICS_KEEP_PAST_DAYS > 0:
        cutoff = now - timedelta(days=C.ICS_KEEP_PAST_DAYS)

    def sort_key(c: Competition):
        ref = _reference_date(c)
        return (ref or datetime.max.replace(tzinfo=C.JST), c.id)

    count = 0
    for comp in sorted(competitions, key=sort_key):
        ref = _reference_date(comp)
        if ref is None:
            continue
        if cutoff and ref < cutoff:
            continue
        # 中身が変わらない限り固定になるタイムスタンプを使う
        stamp_src = parse_iso(comp.first_seen) if comp.first_seen else None
        dtstamp = _utc(stamp_src or ref)
        ev = _event_lines(comp, dtstamp)
        if ev:
            body.extend(ev)
            count += 1

    body.append("END:VCALENDAR")

    folded: list[str] = []
    for line in body:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"


def write(competitions: list[Competition], path=None, now: datetime | None = None) -> int:
    path = path or C.ICS_PATH
    text = build(competitions, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return text.count("BEGIN:VEVENT")
