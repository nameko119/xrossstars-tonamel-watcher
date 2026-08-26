"""静音時間帯（夜間の通知抑制）の判定。

取得・DB更新・ICS生成は夜間も行い、Discordへの通知だけを保留する。
保留した分は、静音時間が明けた最初の実行でまとめて送る。
"""

from __future__ import annotations

from datetime import datetime

from . import config as C


def is_enabled() -> bool:
    if not C.QUIET_HOURS_ENABLED:
        return False
    start, end = C.QUIET_HOURS_START % 24, C.QUIET_HOURS_END % 24
    return start != end


def in_quiet_hours(now: datetime | None = None) -> bool:
    """いま静音時間帯か。境界は「開始時刻ちょうどは静音、終了時刻ちょうどは静音でない」。"""
    if not is_enabled():
        return False
    now = now or datetime.now(C.JST)
    hour = now.astimezone(C.JST).hour
    start, end = C.QUIET_HOURS_START % 24, C.QUIET_HOURS_END % 24
    if start < end:  # 例: 1時〜5時
        return start <= hour < end
    return hour >= start or hour < end  # 例: 23時〜8時（日付をまたぐ）


def window_label() -> str:
    if not is_enabled():
        return "無効"
    return f"{C.QUIET_HOURS_START % 24}時〜{C.QUIET_HOURS_END % 24}時 (JST)"
