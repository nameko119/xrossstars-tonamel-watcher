"""設定値。環境変数で上書き可能。"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# --- 対象URL ---------------------------------------------------------------
LIST_URL = os.environ.get(
    "TONAMEL_LIST_URL",
    "https://tonamel.com/competitions?game=XrossStars&region=JP",
)
COMPETITION_URL_TMPL = "https://tonamel.com/competition/{id}"

# --- タイムゾーン -----------------------------------------------------------
JST = ZoneInfo("Asia/Tokyo")

# --- パス -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEBUG_DIR = ROOT / "debug"
DB_PATH = DATA_DIR / "known_competitions.json"
ICS_PATH = DATA_DIR / "calendar.ics"

# --- スクレイピング挙動 -----------------------------------------------------
# 一覧ページのレンダリング待ち（ミリ秒）
LIST_TIMEOUT_MS = int(os.environ.get("LIST_TIMEOUT_MS", "60000"))
DETAIL_TIMEOUT_MS = int(os.environ.get("DETAIL_TIMEOUT_MS", "45000"))
# 「もっと見る」クリック / 無限スクロールの最大試行回数
MAX_SCROLL_ROUNDS = int(os.environ.get("MAX_SCROLL_ROUNDS", "12"))
# 1回の実行で詳細ページを開く最大件数（初回シード時の暴走防止）
MAX_DETAIL_FETCH = int(os.environ.get("MAX_DETAIL_FETCH", "80"))
# 詳細ページの抽出ロジックの版。ここを上げると、既存の大会も1回だけ取り直す。
#   1 … 初版
#   2 … 会場の住所を address として保存するようにした
DETAIL_VERSION = int(os.environ.get("DETAIL_VERSION", "2"))
# 詳細ページを取得するか
FETCH_DETAIL = os.environ.get("FETCH_DETAIL", "1") not in ("0", "false", "False")
# 詳細ページ間の待ち（秒）: 相手サーバへの配慮
DETAIL_SLEEP_SEC = float(os.environ.get("DETAIL_SLEEP_SEC", "1.5"))

USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)

# --- 通知 -------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
# 日時・会場が変わったときも通知するか
NOTIFY_ON_CHANGE = os.environ.get("NOTIFY_ON_CHANGE", "1") not in ("0", "false", "False")

# --- 静音時間帯（この時間は通知せず、明けたらまとめて送る） -----------------
# JSTの「時」で指定。START <= 時 < END を静音とする（日付をまたぐ指定もOK）。
# QUIET_HOURS_ENABLED=0 で無効化。START と END が同じ値でも無効になる。
QUIET_HOURS_ENABLED = os.environ.get("QUIET_HOURS_ENABLED", "1") not in ("0", "false", "False")
QUIET_HOURS_START = int(os.environ.get("QUIET_HOURS_START", "23"))
QUIET_HOURS_END = int(os.environ.get("QUIET_HOURS_END", "8"))

# --- カレンダー -------------------------------------------------------------
CALENDAR_NAME = os.environ.get("CALENDAR_NAME", "Xrossstars 大会 (Tonamel)")
CALENDAR_DESC = os.environ.get(
    "CALENDAR_DESC", "Tonamel掲載のXrossstars大会を自動収集したカレンダーです。"
)
# 終了からこの日数を過ぎた大会はICSから落とす（0以下で無制限）
ICS_KEEP_PAST_DAYS = int(os.environ.get("ICS_KEEP_PAST_DAYS", "180"))
# 開催時刻が不明な大会の既定の長さ（時間）
DEFAULT_DURATION_HOURS = float(os.environ.get("DEFAULT_DURATION_HOURS", "4"))

# --- デバッグ ---------------------------------------------------------------
DEBUG = os.environ.get("SCRAPER_DEBUG", "0") not in ("0", "false", "False")
