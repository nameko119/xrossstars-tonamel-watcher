"""Discord Webhookへの通知。

- 新着大会をembedで投稿（1メッセージあたり最大10embed）
- 429（レート制限）はretry_afterに従って待って再送
- Webhook未設定でもエラーにせず、スキップした旨を返す
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import config as C
from .dateparse import parse_iso
from .models import Competition

MAX_EMBEDS = 10
COLOR_NEW = 0x4F9DF7      # 新着: 青
COLOR_CHANGED = 0xF5A623  # 変更: オレンジ
COLOR_INFO = 0x9AA0A6     # お知らせ: グレー

_WD = ["月", "火", "水", "木", "金", "土", "日"]


def format_when(comp: Competition) -> str:
    dt = parse_iso(comp.start_at) if comp.start_at else None
    if dt:
        s = f"{dt.year}/{dt.month:02d}/{dt.day:02d}({_WD[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}"
        end = parse_iso(comp.end_at) if comp.end_at else None
        if end:
            if end.date() == dt.date():
                s += f"〜{end.hour:02d}:{end.minute:02d}"
            else:
                s += f" 〜 {end.year}/{end.month:02d}/{end.day:02d} {end.hour:02d}:{end.minute:02d}"
        return s
    if comp.start_date:
        try:
            d = datetime.strptime(comp.start_date, "%Y-%m-%d")
            return f"{d.year}/{d.month:02d}/{d.day:02d}({_WD[d.weekday()]}) 時刻未定"
        except ValueError:
            return comp.start_date
    return "日時不明"


def _embed(comp: Competition, color: int, note: str = "") -> dict:
    fields = [{"name": "📅 日時", "value": format_when(comp), "inline": True}]
    place = comp.venue or comp.format or ""
    if comp.format and comp.venue and comp.format not in comp.venue:
        place = f"{comp.format} / {comp.venue}"
    if place:
        fields.append({"name": "📍 会場", "value": place[:200], "inline": True})
    if comp.entry_fee:
        fields.append({"name": "💴 参加費", "value": comp.entry_fee[:100], "inline": True})
    if comp.capacity:
        fields.append({"name": "👥 定員", "value": comp.capacity[:100], "inline": True})
    if comp.organizer:
        fields.append({"name": "🎤 主催", "value": comp.organizer[:100], "inline": True})
    if comp.entry_period:
        fields.append({"name": "📝 エントリー期間", "value": comp.entry_period[:200], "inline": False})

    embed = {
        "title": (comp.title or f"大会 {comp.id}")[:250],
        "url": comp.url,
        "color": color,
        "fields": fields[:10],
        "footer": {"text": f"Tonamel / ID: {comp.id}"},
    }
    if note:
        embed["description"] = note[:400]
    if comp.image_url.startswith("http"):
        embed["thumbnail"] = {"url": comp.image_url}
    return embed


def _diff_note(old: Competition, new: Competition) -> str:
    labels = {
        "title": "大会名", "start_at": "開始日時", "end_at": "終了日時",
        "start_date": "開催日", "format": "開催形式", "venue": "会場",
        "entry_fee": "参加費", "capacity": "定員", "organizer": "主催",
    }
    def show(key: str, value: str) -> str:
        if not value:
            return "—"
        if key in ("start_at", "end_at"):
            dt = parse_iso(value)
            if dt:
                return f"{dt.year}/{dt.month:02d}/{dt.day:02d}({_WD[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}"
        return value

    lines = []
    for key, label in labels.items():
        o, n = getattr(old, key) or "", getattr(new, key) or ""
        if o != n:
            lines.append(f"・{label}: `{show(key, o)}` → `{show(key, n)}`")
    return "**変更あり**\n" + "\n".join(lines[:6]) if lines else "**変更あり**"


def _post(webhook: str, payload: dict, retries: int = 3) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "xrossstars-tonamel-watcher/1.0"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                if 200 <= res.status < 300:
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode()).get("retry_after", 5))
                except Exception:
                    wait = 5.0
                time.sleep(min(wait + 0.5, 30))
                continue
            if 500 <= e.code < 600:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"[discord] HTTPエラー {e.code}: {e.reason}")
            return False
        except urllib.error.URLError as e:
            print(f"[discord] 接続エラー: {e.reason}")
            time.sleep(2 * (attempt + 1))
    return False


diff_note = _diff_note  # 外から使えるように別名を用意


def notify(
    new_items: list[Competition],
    changed_items: list[tuple[Competition, str]] | None = None,
    seed_count: int | None = None,
    seed_samples: list[Competition] | None = None,
    deferred: bool = False,
    webhook: str | None = None,
) -> dict:
    """Discordへ通知する。

    Args:
        new_items: 新着として知らせる大会。
        changed_items: (大会, 変更内容の文面) のリスト。
        seed_count: 初回シードのときの件数。Noneなら通常通知。
        seed_samples: 初回シードで例示する大会（最大5件）。
        deferred: 静音時間帯に保留していた分をまとめて送る場合True。
    """
    changed_items = changed_items or []
    webhook = (webhook if webhook is not None else C.DISCORD_WEBHOOK_URL).strip()
    summary = {"sent": 0, "skipped_reason": None}

    if not webhook:
        summary["skipped_reason"] = "DISCORD_WEBHOOK_URL が未設定のため通知をスキップしました"
        print("[discord] " + summary["skipped_reason"])
        return summary

    # 初回はDBが空＝全件が「新着」になるので、個別通知はせず1通のまとめだけ送る
    if seed_count is not None:
        ok = _post(webhook, {
            "content": (
                f"✅ **Xrossstars大会ウォッチャーを開始しました**\n"
                f"現在Tonamelに掲載中の大会 **{seed_count}件** を初期登録しました。"
                f"次回以降、新しく掲載された大会だけをお知らせします。"
            ),
            "embeds": [_embed(c, COLOR_INFO) for c in (seed_samples or [])[:5]],
        })
        summary["sent"] += int(ok)
        # シードと同時に送るものは無い（全件がシード扱いのため）
        return summary

    embeds: list[dict] = [_embed(c, COLOR_NEW) for c in new_items]
    if C.NOTIFY_ON_CHANGE:
        embeds += [_embed(c, COLOR_CHANGED, note) for c, note in changed_items]

    if not embeds:
        return summary

    header = []
    if deferred:
        header.append("🌙 **夜間にみつかった分のまとめ**")
    if new_items:
        header.append(f"🆕 新着大会 **{len(new_items)}件**")
    if C.NOTIFY_ON_CHANGE and changed_items:
        header.append(f"✏️ 内容変更 **{len(changed_items)}件**")

    for i in range(0, len(embeds), MAX_EMBEDS):
        chunk = embeds[i: i + MAX_EMBEDS]
        payload = {"embeds": chunk}
        if i == 0:
            payload["content"] = " / ".join(header)
        if _post(webhook, payload):
            summary["sent"] += 1
        time.sleep(1.0)  # 連投のレート制限対策

    return summary
