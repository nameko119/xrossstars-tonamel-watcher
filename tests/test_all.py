"""ネットに出ずに動く自己テスト。

  python -m tests.test_all

日付パース・差分検知・ICS生成・JSON探索を、実際に起こりそうな
表記ゆれのサンプルで確認する。
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import build_ics                      # noqa: E402
from src.config import JST                     # noqa: E402
from src.dateparse import parse_datetime_range, parse_any  # noqa: E402
from src.models import Competition             # noqa: E402
from src.scrape import (                       # noqa: E402
    competition_from_json, enrich_from_text, index_json_by_id, COMPETITION_ID_RE,
)
from src.store import Store                    # noqa: E402

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=JST)
failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}\n      期待: {expected!r}\n      実際: {actual!r}")
        failures.append(label)


def check_true(label: str, cond, hint="") -> None:
    check(label + (f" ({hint})" if hint else ""), bool(cond), True)


# ---------------------------------------------------------------- 日付パース
def test_dates() -> None:
    print("\n[1] 日時パース")
    cases = [
        ("2026/09/05 13:00", "2026-09-05T13:00:00+09:00", None),
        ("2026年9月5日(土) 13:00", "2026-09-05T13:00:00+09:00", None),
        ("2026-09-05T13:00:00+09:00", "2026-09-05T13:00:00+09:00", None),
        ("９月５日（土） １３：００", "2026-09-05T13:00:00+09:00", None),
        ("9/5 13:00 〜 18:00", "2026-09-05T13:00:00+09:00", "2026-09-05T18:00:00+09:00"),
        ("2026/09/05 22:00〜2026/09/06 02:00", "2026-09-05T22:00:00+09:00", "2026-09-06T02:00:00+09:00"),
        ("2026/09/05 13時", "2026-09-05T13:00:00+09:00", None),
        ("開催日時: 2026/12/31 21:00 〜 23:30", "2026-12-31T21:00:00+09:00", "2026-12-31T23:30:00+09:00"),
    ]
    for text, exp_start, exp_end in cases:
        s, e, _ = parse_datetime_range(text, now=NOW)
        check(f"開始 {text!r}", s.isoformat() if s else None, exp_start)
        if exp_end:
            check(f"終了 {text!r}", e.isoformat() if e else None, exp_end)

    # 年省略：来年に繰り越すべきケース
    s, _, _ = parse_datetime_range("1/10 13:00", now=NOW)
    check("年省略は未来側の年を選ぶ", s.year if s else None, 2027)
    s, _, _ = parse_datetime_range("8/20 13:00", now=NOW)
    check("直近の過去は今年のまま", s.year if s else None, 2026)

    # 時刻なし → 日付のみ
    s, e, d = parse_datetime_range("2026年9月5日(土)", now=NOW)
    check("時刻なしは start=None", s, None)
    check("時刻なしでも日付は取れる", d, "2026-09-05")

    # 日跨ぎ
    s, e, _ = parse_datetime_range("9/5 22:00〜1:00", now=NOW)
    check("日跨ぎの終了は翌日", e.isoformat() if e else None, "2026-09-06T01:00:00+09:00")

    # ISO / epoch
    check("epoch秒", parse_any(1772000000).isoformat(), "2026-02-25T15:13:20+09:00")
    check("epochミリ秒", parse_any(1772000000000).isoformat(), "2026-02-25T15:13:20+09:00")
    check("Z付きISO", parse_any("2026-09-05T04:00:00Z").isoformat(), "2026-09-05T13:00:00+09:00")
    check("パース不能はNone", parse_any("未定"), None)
    check("小さすぎる数値は日時扱いしない", parse_any(12345), None)


# ------------------------------------------------------------ JSON横取り解析
def test_json_index() -> None:
    print("\n[2] APIレスポンスからの抽出")
    payload = {
        "data": {
            "competitions": {
                "nodes": [
                    {
                        "id": "abc12",
                        "title": "第3回 クロススターズ杯",
                        "startAt": "2026-09-05T13:00:00+09:00",
                        "endAt": "2026-09-05T18:00:00+09:00",
                        "isOnline": False,
                        "place": "秋葉原ベルサール",
                        "entryFee": 1000,
                        "capacity": 32,
                        "organizer": {"name": "なめこ商会"},
                        "imageUrl": "https://example.com/a.png",
                    },
                    {"id": "zzz99", "title": "無関係な大会", "startAt": "2026-01-01T00:00:00+09:00"},
                ]
            }
        }
    }
    idx = index_json_by_id([payload], {"abc12"})
    check("対象IDだけ拾う", sorted(idx), ["abc12"])

    comp = competition_from_json("abc12", idx["abc12"])
    check("タイトル", comp.title, "第3回 クロススターズ杯")
    check("開始", comp.start_at, "2026-09-05T13:00:00+09:00")
    check("終了", comp.end_at, "2026-09-05T18:00:00+09:00")
    check("開催形式", comp.format, "オフライン")
    check("会場", comp.venue, "秋葉原ベルサール")
    check("参加費", comp.entry_fee, "1000円")
    check("定員", comp.capacity, "32人")
    check("主催（ネストしたdict）", comp.organizer, "なめこ商会")
    check("URL", comp.url, "https://tonamel.com/competition/abc12")

    # キー名がスネークケースでも拾えること
    idx2 = index_json_by_id([{"competition_id": "snake1", "name": "スネーク杯",
                             "start_at": 1772000000, "is_online": True}], {"snake1"})
    c2 = competition_from_json("snake1", idx2["snake1"])
    check("スネークケースのタイトル", c2.title, "スネーク杯")
    check("スネークケースの日時", c2.start_at, "2026-02-25T15:13:20+09:00")
    check("オンライン判定", c2.format, "オンライン")

    check_true("大会IDの正規表現", COMPETITION_ID_RE.search("/competition/aB3-x_9?tab=1"))
    check("大会ID抽出", COMPETITION_ID_RE.search("https://tonamel.com/competition/aB3x9").group(1), "aB3x9")


# ------------------------------------------------------------ DOMテキスト補完
def test_text_enrich() -> None:
    print("\n[3] 画面テキストからの補完")
    text = (
        "非公式 クロススターズ交流会 vol.5\n"
        "2026年10月12日(月) 10:00\n"
        "会場: 大阪日本橋 カードショップABC\n"
        "参加費: 500円\n"
        "定員: 16名\n"
        "主催: てすと太郎\n"
        "エントリー期間: 2026/09/20 12:00 〜 2026/10/10 23:59\n"
    )
    comp = enrich_from_text(Competition(id="t1", url="u"), text, NOW)
    check("日時", comp.start_at, "2026-10-12T10:00:00+09:00")
    check("会場", comp.venue, "大阪日本橋 カードショップABC")
    check("参加費", comp.entry_fee, "500円")
    check("定員", comp.capacity, "16名")
    check("主催", comp.organizer, "てすと太郎")
    check("形式（会場ありでオフライン判定）", comp.format, "オフライン")
    check("タイトル（先頭行）", comp.title, "非公式 クロススターズ交流会 vol.5")
    check("エントリー期間", comp.entry_period, "2026/09/20 12:00 〜 2026/10/10 23:59")

    # 既存の値は壊さない
    pre = Competition(id="t2", url="u", title="既存タイトル", start_at="2026-01-01T00:00:00+09:00")
    after = enrich_from_text(pre, text, NOW)
    check("既存タイトルを上書きしない", after.title, "既存タイトル")
    check("既存日時を上書きしない", after.start_at, "2026-01-01T00:00:00+09:00")

    # オンライン表記
    online = enrich_from_text(Competition(id="t3", url="u"), "オンライン大会\n2026/11/03 20:00\n", NOW)
    check("オンライン判定", online.format, "オンライン")


# ------------------------------------------------------------------ 差分検知
def test_store() -> None:
    print("\n[4] 差分検知")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "db.json"
        store = Store(db)

        a = Competition(id="a1", url="u/a1", title="大会A", start_at="2026-09-05T13:00:00+09:00")
        b = Competition(id="b2", url="u/b2", title="大会B", start_at="2026-09-06T13:00:00+09:00")

        d1 = store.apply([a, b])
        check("初回は全件が新規", len(d1.new), 2)
        check("初回はシード扱い", d1.is_seed, True)
        store.save()

        # 2回目：同じ内容 → 変化なし
        store2 = Store(db)
        check("保存して読み直せる", len(store2.competitions), 2)
        d2 = store2.apply([Competition.from_dict(a.to_dict()), Competition.from_dict(b.to_dict())])
        check("再取得で新規は出ない", len(d2.new), 0)
        check("変更も出ない", len(d2.changed), 0)
        check("シードではない", d2.is_seed, False)
        check("変化なし件数", d2.unchanged, 2)

        # 3回目：Bの日時変更 + 新規C
        b2 = Competition.from_dict(b.to_dict())
        b2.start_at = "2026-09-07T13:00:00+09:00"
        c = Competition(id="c3", url="u/c3", title="大会C", start_date="2026-10-01")
        d3 = store2.apply([Competition.from_dict(a.to_dict()), b2, c])
        check("新規を1件検知", [x.id for x in d3.new], ["c3"])
        check("変更を1件検知", [n.id for _, n in d3.changed], ["b2"])
        check("SEQUENCEが増える", store2.competitions["b2"].seq, 1)
        check("first_seenが保持される", bool(store2.competitions["b2"].first_seen), True)

        # 一覧から消えてもDBには残る
        d4 = store2.apply([Competition.from_dict(a.to_dict())])
        check("消えた大会もDBに残る", len(store2.competitions), 3)
        check("消えただけでは通知しない", d4.has_updates, False)

        # 部分的な情報しかない再取得でも既存を壊さない
        partial = Competition(id="a1", url="u/a1")  # タイトルも日時も空
        store2.apply([partial])
        check("空フィールドで既存を消さない", store2.competitions["a1"].title, "大会A")

        # 壊れたJSONからの復旧
        db.write_text("{壊れている", encoding="utf-8")
        store3 = Store(db)
        check("壊れたDBは空で作り直す", len(store3.competitions), 0)
        check("壊れたDBは退避される", db.with_suffix(".broken.json").exists(), True)


# -------------------------------------------------------------------- ICS
def test_ics() -> None:
    print("\n[5] ICS生成")
    comps = [
        Competition(
            id="a1", url="https://tonamel.com/competition/a1",
            title="第3回 クロススターズ杯; テスト, 記号\\入り",
            start_at="2026-09-05T13:00:00+09:00", end_at="2026-09-05T18:00:00+09:00",
            format="オフライン", venue="秋葉原ベルサール", organizer="なめこ商会",
            entry_fee="1000円", capacity="32人", first_seen="2026-08-01T00:00:00+09:00",
        ),
        Competition(
            id="b2", url="https://tonamel.com/competition/b2", title="時刻未定の大会",
            start_date="2026-10-01", first_seen="2026-08-01T00:00:00+09:00",
        ),
        Competition(
            id="c3", url="https://tonamel.com/competition/c3", title="オンライン大会",
            start_at="2026-11-03T20:00:00+09:00", format="オンライン",
            first_seen="2026-08-01T00:00:00+09:00",
        ),
        Competition(id="d4", url="u", title="日付不明", first_seen="2026-08-01T00:00:00+09:00"),
        Competition(id="e5", url="u", title="大昔の大会", start_date="2020-01-01",
                    first_seen="2020-01-01T00:00:00+09:00"),
    ]
    text = build_ics.build(comps, now=NOW)

    check("イベント数（日付不明と古い大会は除外）", text.count("BEGIN:VEVENT"), 3)
    check_true("VCALENDARで始まる", text.startswith("BEGIN:VCALENDAR\r\n"))
    check_true("VCALENDARで終わる", text.rstrip().endswith("END:VCALENDAR"))
    check("改行はすべてCRLF", text.replace("\r\n", "").count("\n"), 0)
    check_true("UIDが入る", "UID:tonamel-a1@xrossstars-watcher" in text)
    check_true("UTCに変換される", "DTSTART:20260905T040000Z" in text, "13:00 JST = 04:00 UTC")
    check_true("終了時刻", "DTEND:20260905T090000Z" in text)
    check_true("終日イベント", "DTSTART;VALUE=DATE:20261001" in text)
    check_true("終日の終了は翌日", "DTEND;VALUE=DATE:20261002" in text)
    check_true("セミコロンがエスケープされる", "\\;" in text)
    check_true("カンマがエスケープされる", "\\," in text)
    check_true("バックスラッシュがエスケープされる", "\\\\" in text)
    check_true("カレンダー名", "X-WR-CALNAME:" in text)
    check_true("URLプロパティ", "URL:https://tonamel.com/competition/a1" in text)
    unfolded = text.replace("\r\n ", "")  # 折り返しを戻してから中身を見る
    check_true("説明に主催が入る", "なめこ商会" in unfolded)
    check_true("説明に参加費が入る", "1000円" in unfolded)
    check_true("会場がLOCATIONに入る", "LOCATION:秋葉原ベルサール" in unfolded)
    check_true("オンラインに印がつく", "🟦" in text)

    # 75オクテット折り返し
    over = [l for l in text.split("\r\n") if len(l.encode("utf-8")) > 75]
    check("75オクテット超の行が無い", over, [])
    # 継続行は必ず空白始まり
    lines = text.split("\r\n")
    bad = [l for l in lines if l and not l[0].isspace() and ":" not in l and ";" not in l]
    check("プロパティ行の形式", bad, [])

    # 2回生成しても同じ（gitの差分が無駄に出ない）
    check("生成結果が安定している", build_ics.build(comps, now=NOW), text)

    # 実際に書き出せること
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "calendar.ics"
        n = build_ics.write(comps, path=p, now=NOW)
        check("書き出し件数", n, 3)
        check("ファイルの改行がCRLFのまま", p.read_bytes().count(b"\r\n") > 20, True)


# ------------------------------------------------------------ fixture経路
def test_fixture_run() -> None:
    print("\n[6] fixtureでの通し実行")
    from src import config as C
    from src.main import main

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fixture = tmp / "fixture.json"
        fixture.write_text(json.dumps({"competitions": [
            {"id": "f1", "url": "https://tonamel.com/competition/f1", "title": "フィクスチャ大会",
             "start_at": "2026-09-30T13:00:00+09:00", "format": "オンライン"},
        ]}, ensure_ascii=False), encoding="utf-8")

        orig_db, orig_ics = C.DB_PATH, C.ICS_PATH
        C.DB_PATH, C.ICS_PATH = tmp / "db.json", tmp / "calendar.ics"
        try:
            rc = main(["--fixture", str(fixture), "--no-discord"])
            check("終了コード0", rc, 0)
            check("DBが作られる", C.DB_PATH.exists(), True)
            check("ICSが作られる", C.ICS_PATH.exists(), True)
            saved = json.loads(C.DB_PATH.read_text(encoding="utf-8"))
            check("DBに1件入る", list(saved["competitions"]), ["f1"])
            check_true("ICSにイベントが入る", "BEGIN:VEVENT" in C.ICS_PATH.read_text(encoding="utf-8"))
        finally:
            C.DB_PATH, C.ICS_PATH = orig_db, orig_ics


# ------------------------------------------------------------ 静音時間帯
def test_quiet_hours() -> None:
    print("\n[7] 静音時間帯")
    from src import config as C
    from src import quiet

    orig = (C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END)
    try:
        C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END = True, 23, 8

        def at(h):
            return quiet.in_quiet_hours(datetime(2026, 8, 26, h, 30, tzinfo=JST))

        check("22時台は通知する", at(22), False)
        check("23時ちょうどから静音", quiet.in_quiet_hours(datetime(2026, 8, 26, 23, 0, tzinfo=JST)), True)
        check("23時台は静音", at(23), True)
        check("深夜2時は静音", at(2), True)
        check("7時台は静音", at(7), True)
        check("8時ちょうどは静音でない", quiet.in_quiet_hours(datetime(2026, 8, 26, 8, 0, tzinfo=JST)), False)
        check("8時台は通知する", at(8), False)
        check("正午は通知する", at(12), False)
        check("表示ラベル", quiet.window_label(), "23時〜8時 (JST)")

        # 日付をまたがない指定
        C.QUIET_HOURS_START, C.QUIET_HOURS_END = 1, 5
        check("1〜5時指定: 0時は通知する", at(0), False)
        check("1〜5時指定: 3時は静音", at(3), True)
        check("1〜5時指定: 5時は通知する", at(5), False)

        # 無効化
        C.QUIET_HOURS_ENABLED = False
        check("無効なら常に通知する", at(3), False)
        C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END = True, 3, 3
        check("開始と終了が同じなら無効", at(3), False)
    finally:
        C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END = orig


def test_pending() -> None:
    print("\n[8] 通知の保留と朝の一括送信")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "db.json"
        store = Store(db)

        a = Competition(id="a1", url="u/a1", title="夜に出た大会A", start_at="2026-09-05T13:00:00+09:00")
        b = Competition(id="b2", url="u/b2", title="夜に出た大会B", start_date="2026-09-06")
        store.apply([a, b])
        check("最初は保留なし", store.has_pending, False)

        # 1回目の夜間実行：新着2件を保留
        store.defer(["a1", "b2"], [])
        check("保留された", store.has_pending, True)
        check("保留件数", store.pending_counts(), (None, 2, 0))
        store.save()

        # 保留はファイルに残る
        store = Store(db)
        check("保存後も保留が残る", store.pending_counts(), (None, 2, 0))

        # 2回目の夜間実行：同じ大会をもう一度積んでも増えない
        store.defer(["a1"], [("a1", "**変更あり**")])
        check("重複は積まない", store.pending_counts(), (None, 2, 0))

        # 別の大会の変更を積む
        c = Competition(id="c3", url="u/c3", title="既存の大会C", start_date="2026-09-10")
        store.apply([c])
        store.defer([], [("c3", "**変更あり**\n・会場が変わりました")])
        check("変更を積む", store.pending_counts(), (None, 2, 1))

        # 朝：保留分を最新のDB内容で取り出す
        seed, new, changed = store.peek_pending()
        check("シードなし", seed, None)
        check("新着2件を復元", [c.id for c in new], ["a1", "b2"])
        check("変更1件を復元", [(c.id, n.splitlines()[0]) for c, n in changed],
              [("c3", "**変更あり**")])
        check("peekでは消えない", store.has_pending, True)
        store.clear_pending()
        check("clearで消える", store.has_pending, False)

        # DBから消えたIDは黙って捨てる
        store.defer(["存在しないID"], [])
        _, new2, _ = store.peek_pending()
        check("不明なIDは捨てる", new2, [])
        store.clear_pending()

        # シードの保留は件数だけ
        store.defer([], [], seed_count=12)
        check("シード件数を保留", store.pending_counts(), (12, 0, 0))
        seed, new3, _ = store.peek_pending()
        check("シードは個別通知しない", (seed, new3), (12, []))

        # 保留の上限
        store.clear_pending()
        store.defer([f"id{i}" for i in range(300)], [])
        check("保留は上限で頭を落とす", store.pending_counts()[1], Store.MAX_PENDING)


def test_quiet_end_to_end() -> None:
    print("\n[9] 夜→朝の通し動作（通知は送らず記録だけ）")
    from src import config as C
    from src import main as main_mod
    from src.store import Store as S

    sent_log: list[dict] = []

    def fake_notify(new_items, changed_items=None, seed_count=None,
                    seed_samples=None, deferred=False, webhook=None):
        sent_log.append({
            "new": [c.id for c in new_items],
            "changed": [c.id for c, _ in (changed_items or [])],
            "seed": seed_count,
            "deferred": deferred,
        })
        return {"sent": 1, "skipped_reason": None}

    class Args:
        no_discord = False
        ignore_quiet = False

    orig_notify = main_mod.notify
    orig_quiet = main_mod.in_quiet_hours
    orig_cfg = (C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END)
    try:
        main_mod.notify = fake_notify
        C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END = True, 23, 8

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.json"

            # --- 夜1回目：初回シード ---
            main_mod.in_quiet_hours = lambda: True
            store = S(db)
            d = store.apply([Competition(id=f"s{i}", url="u", title=f"既存{i}",
                                         start_date="2026-09-01") for i in range(5)])
            main_mod._handle_notifications(store, d, Args())
            store.save()
            check("夜のシードは送らない", sent_log, [])
            check("シード件数を保留", S(db).pending_counts(), (5, 0, 0))

            # --- 夜2回目：新着1件 ---
            store = S(db)
            d = store.apply([Competition(id="n1", url="u", title="夜の新着",
                                         start_date="2026-09-20")])
            main_mod._handle_notifications(store, d, Args())
            store.save()
            check("夜の新着も送らない", sent_log, [])
            check("シードと新着が両方たまる", S(db).pending_counts(), (5, 1, 0))

            # --- 朝：まとめて送る ---
            main_mod.in_quiet_hours = lambda: False
            store = S(db)
            d = store.apply([Competition(id="m1", url="u", title="朝の新着",
                                         start_date="2026-09-21")])
            main_mod._handle_notifications(store, d, Args())
            store.save()

            check("朝に3通送る（シード / 夜の分 / 朝の分）", len(sent_log), 3)
            check("1通目はシード", (sent_log[0]["seed"], sent_log[0]["new"]), (5, []))
            check("2通目は夜の保留分", (sent_log[1]["new"], sent_log[1]["deferred"]), (["n1"], True))
            check("3通目は朝の新着", (sent_log[2]["new"], sent_log[2]["deferred"]), (["m1"], False))
            check("保留は空になる", S(db).has_pending, False)

            # --- 夜でも --ignore-quiet ならすぐ送る ---
            sent_log.clear()
            main_mod.in_quiet_hours = lambda: True
            args = Args()
            args.ignore_quiet = True
            store = S(db)
            d = store.apply([Competition(id="x1", url="u", title="手動確認",
                                         start_date="2026-09-22")])
            main_mod._handle_notifications(store, d, args)
            check("--ignore-quiet ならすぐ送る", [s["new"] for s in sent_log], [["x1"]])

            # --- 送信に失敗したら保留を消さない ---
            sent_log.clear()
            main_mod.notify = lambda *a, **k: {"sent": 0, "skipped_reason": "webhook未設定"}
            main_mod.in_quiet_hours = lambda: True
            store = S(db)
            d = store.apply([Competition(id="y1", url="u", title="夜の新着2",
                                         start_date="2026-09-23")])
            main_mod._handle_notifications(store, d, Args())
            store.save()
            main_mod.in_quiet_hours = lambda: False
            store = S(db)
            main_mod._handle_notifications(store, store.apply([]), Args())
            store.save()
            check("送信失敗なら保留を持ち越す", S(db).pending_counts()[1], 1)
    finally:
        main_mod.notify = orig_notify
        main_mod.in_quiet_hours = orig_quiet
        C.QUIET_HOURS_ENABLED, C.QUIET_HOURS_START, C.QUIET_HOURS_END = orig_cfg


# ------------------------------------------------------------ 正規化
def test_normalize() -> None:
    print("\n[10] 検索用データの正規化")
    from src.normalize import (
        detect_online, detect_prefecture, normalize, parse_count, parse_fee,
    )

    check("「32名」", parse_count("32名"), 32)
    check("「16人」", parse_count("16人"), 16)
    check("「24チーム」", parse_count("24チーム"), 24)
    check("全角「３２名」", parse_count("３２名"), 32)
    check("「1,024名」", parse_count("1,024名"), 1024)
    check("数字だけ", parse_count("32"), 32)
    check("「無制限」はNone", parse_count("無制限"), None)
    check("「定員なし」はNone", parse_count("定員なし"), None)
    check("空はNone", parse_count(""), None)

    check("「1000円」", parse_fee("1000円"), 1000)
    check("「1,500円」", parse_fee("1,500円"), 1500)
    check("「無料」は0", parse_fee("無料"), 0)
    check("「0円」は0", parse_fee("0円"), 0)
    check("全角「１０００円」", parse_fee("１０００円"), 1000)
    check("読めない文字列はNone", parse_fee("応相談"), None)

    check("都道府県が書いてある", detect_prefecture("大阪府大阪市 なんば"), "大阪府")
    check("接尾辞なし", detect_prefecture("東京 新宿区"), "東京都")
    check("地名から推定", detect_prefecture("秋葉原ベルサール"), "東京都")
    check("札幌→北海道", detect_prefecture("札幌市中央区"), "北海道")
    check("天神→福岡県", detect_prefecture("天神ビル 会議室A"), "福岡県")
    check("京都市→京都府", detect_prefecture("京都市中京区 四条烏丸"), "京都府")
    check("東京都と京都府を取り違えない", detect_prefecture("東京都渋谷区"), "東京都")
    check("手がかりなしはNone", detect_prefecture("カードショップABC"), None)
    check("1文字地名で誤爆しない", detect_prefecture("栄光カップ"), None)

    check("オンライン判定", detect_online("オンライン"), True)
    check("オフライン判定", detect_online("", "秋葉原ベルサール 会場"), False)
    check("既存の値を尊重", detect_online("", "", existing="オンライン"), True)
    check("手がかりなしはNone", detect_online("", ""), None)

    on = normalize(Competition(id="a", url="u", format="オンライン",
                               entry_fee="無料", capacity="16名"))
    check("オンラインは都道府県なし", (on.is_online, on.prefecture, on.region), (True, "", ""))
    check("正規化: 参加費", on.fee_num, 0)
    check("正規化: 定員", on.capacity_num, 16)

    off = normalize(Competition(id="b", url="u", format="オフライン",
                                venue="愛知県名古屋市 大須ホール",
                                entry_fee="2000円", capacity="128名"))
    check("正規化: 都道府県", off.prefecture, "愛知県")
    check("正規化: 地方", off.region, "中部")
    check("正規化: 参加費", off.fee_num, 2000)

    # 派生フィールドは差分検知に影響しない（＝勝手に「変更あり」通知が出ない）
    before = Competition(id="c", url="u", title="大会", venue="東京都", capacity="32名")
    sig_before = before.signature()
    normalize(before)
    check("正規化しても差分は出ない", before.signature(), sig_before)


# ------------------------------------------------------------ 検索
def _sample() -> list[Competition]:
    from src.normalize import normalize_all

    raw = json.loads((Path(__file__).parent / "sample_data.json").read_text(encoding="utf-8"))
    comps = [Competition.from_dict(d) for d in raw["competitions"].values()]
    normalize_all(comps)
    return comps


def test_search() -> None:
    print("\n[11] 検索")
    from datetime import date as _date

    from src.search import Query, count, period_range, search

    comps = _sample()
    today = _date(2026, 8, 26)

    def ids(q: Query) -> list[str]:
        return [c.id for c in search(comps, q, today=today)]

    check("サンプル件数", len(comps), 12)

    # 既定：今後の大会のみ（過去のsmp011は出ない）、日付不明のsmp012は出る
    base = ids(Query())
    check("過去の大会は既定で出ない", "smp011" in base, False)
    check("日付不明は既定で出る", "smp012" in base, True)
    check("日付順に並ぶ", base[:3], ["smp001", "smp002", "smp005"])

    check("過去も含める", "smp011" in ids(Query(include_past=True)), True)
    check("新しい順", ids(Query(sort="-date", include_past=True))[0], "smp010")

    # キーワード
    check("キーワード（大会名）", ids(Query(text="初心者")), ["smp002", "smp009"])
    check("キーワード（会場）", ids(Query(text="大須")), ["smp006"])
    check("キーワード（主催者）", ids(Query(text="なめこ商会")),
          ["smp001", "smp009", "smp012"])
    check("AND検索", ids(Query(text="オンライン 初心者")), ["smp002", "smp009"])
    check("大文字小文字・全角を無視", ids(Query(text="ＶＯＬ.9")), ["smp002"])
    check("該当なし", ids(Query(text="存在しない大会")), [])

    # 地域・形式
    check("都道府県", ids(Query(prefectures=["東京都"])), ["smp001"])
    check("略称でも引ける", ids(Query(prefectures=["東京"])), ["smp001"])
    check("複数指定", ids(Query(prefectures=["大阪", "愛知"])), ["smp003", "smp006"])
    check("地方", ids(Query(region="関西")), ["smp003", "smp010"])
    check("オンラインのみ", ids(Query(online=True)), ["smp002", "smp005", "smp009"])
    check("オフラインのみ", ids(Query(online=False)),
          ["smp001", "smp003", "smp004", "smp006", "smp007", "smp008", "smp010"])

    # 人数・参加費
    check("定員16人以上", ids(Query(capacity_min=16, online=False)),
          ["smp001", "smp003", "smp004", "smp006", "smp007", "smp008", "smp010"])
    check("定員32人以上", ids(Query(capacity_min=32)),
          ["smp001", "smp003", "smp006", "smp008", "smp010"])
    check("定員16人以下", ids(Query(capacity_max=16)), ["smp002", "smp005", "smp004"])
    check("無料のみ", ids(Query(fee_max=0)), ["smp002", "smp005", "smp009"])
    check("1000円以下", ids(Query(fee_max=1000)),
          ["smp001", "smp002", "smp005", "smp004", "smp009", "smp008", "smp010"])
    check("主催者", ids(Query(organizer="XSオンライン部")), ["smp002", "smp005"])

    # 期間
    f, t = period_range("今月", today)
    check("今月の範囲", (f, t), ("2026-08-26", "2026-08-31"))
    f, t = period_range("来月", today)
    check("来月の範囲", (f, t), ("2026-09-01", "2026-09-30"))
    check("来月の大会", ids(Query(date_from=f, date_to=t)),
          ["smp001", "smp002", "smp005", "smp003", "smp004", "smp009"])
    f, t = period_range("今週末", today)
    check("今週末の範囲", (f, t), ("2026-08-29", "2026-08-30"))
    check("期間指定では日付不明を含めない", "smp012" in ids(Query(date_from="2026-09-01")), False)

    # 組み合わせ
    check("関西 かつ 1500円以下",
          ids(Query(region="関西", fee_max=1500)), ["smp003", "smp010"])
    check("オンライン かつ 無料 かつ 定員8人以上",
          ids(Query(online=True, fee_max=0, capacity_min=8)), ["smp002", "smp005"])

    # 件数とページング
    q = Query(online=False)
    check("count はページングを無視する", count(comps, q, today), 7)
    check("limit", len(search(comps, Query(online=False, limit=3), today)), 3)
    check("offset", [c.id for c in search(comps, Query(online=False, limit=2, offset=2), today)],
          ["smp004", "smp006"])


# ------------------------------------------------------------ Webページ生成
def test_build_site() -> None:
    print("\n[12] Webページの生成")
    from src import build_site

    comps = _sample()
    html = build_site.build(comps, now=NOW)

    check_true("完全なHTMLになっている", html.startswith("<!doctype html>"))
    check_true("日本語ページとして宣言", 'lang="ja"' in html)
    check_true("スマホ向けの指定", 'name="viewport"' in html)
    check_true("タイトル", "<title>Xrossstars 大会ファインダー</title>" in html)
    check_true("検索ロジックが埋め込まれている", "const XSSearch" in html)
    check_true("Node用の行は入らない", "module.exports" not in html)
    check_true("データが埋め込まれている", "window.__XS_DATA__" in html)
    check_true("明暗どちらの配色も定義されている",
               "prefers-color-scheme: dark" in html and '[data-theme="dark"]' in html)
    check_true("背景色を明示している", "background: var(--ground)" in html)

    # 埋め込みデータに余計なものが混ざっていないか
    import re as _re
    m = _re.search(r"window\.__XS_DATA__ = (.*?);</script>", html, _re.S)
    payload = json.loads(m.group(1))
    check("埋め込み件数", len(payload["competitions"]), 12)
    check("公開する項目", sorted(payload["competitions"][0]),
          sorted(build_site.EXPORT_FIELDS))
    check_true("生HTMLやデバッグ情報は載せない",
               all("raw_text" not in c and "raw_json" not in c
                   for c in payload["competitions"]))
    check("正規化済みの値が入っている",
          [c["prefecture"] for c in payload["competitions"] if c["id"] == "smp003"],
          ["大阪府"])

    # </script> でHTMLが壊れないこと（大会名に紛れ込んだ場合の対策）
    danger = Competition(id="x", url="u", title="</script><b>壊す</b>", start_date="2026-09-09")
    from src.normalize import normalize as _norm
    bad_html = build_site.build([_norm(danger)], now=NOW)
    check_true("大会名のHTMLでページが壊れない", "</script><b>" not in bad_html)

    # Artifact用の断片
    frag = build_site.build(comps, fragment=True, now=NOW)
    check_true("断片版にはdoctypeが無い", not frag.lstrip().startswith("<!doctype"))
    check_true("断片版もタイトルから始まる", frag.lstrip().startswith("<title>"))

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "index.html"
        n = build_site.write(comps, path=p, now=NOW)
        check("書き出し件数", n, 12)
        check_true("ファイルができる", p.exists() and p.stat().st_size > 10_000)


def test_pipeline_outputs() -> None:
    print("\n[13] 実行するとICSとWebページが両方できる")
    from src import build_site, config as C
    from src.main import main

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fixture = tmp / "fx.json"
        fixture.write_text(json.dumps({"competitions": [{
            "id": "p1", "url": "https://tonamel.com/competition/p1",
            "title": "パイプライン確認用", "start_at": "2026-09-30T13:00:00+09:00",
            "format": "オフライン", "venue": "東京都渋谷区", "entry_fee": "500円",
            "capacity": "24名",
        }]}, ensure_ascii=False), encoding="utf-8")

        orig = (C.DB_PATH, C.ICS_PATH, build_site.SITE_PATH)
        C.DB_PATH, C.ICS_PATH = tmp / "db.json", tmp / "calendar.ics"
        build_site.SITE_PATH = tmp / "index.html"
        try:
            rc = main(["--fixture", str(fixture), "--no-discord"])
            check("終了コード0", rc, 0)
            check_true("ICSができる", C.ICS_PATH.exists())
            check_true("Webページができる", build_site.SITE_PATH.exists())
            saved = json.loads(C.DB_PATH.read_text(encoding="utf-8"))
            rec = saved["competitions"]["p1"]
            check("DBに都道府県が入る", rec["prefecture"], "東京都")
            check("DBに地方が入る", rec["region"], "関東")
            check("DBに定員の人数が入る", rec["capacity_num"], 24)
            check("DBに参加費の金額が入る", rec["fee_num"], 500)
            check("DBにオンライン判定が入る", rec["is_online"], False)
            check_true("Webページにその大会が載る",
                       "パイプライン確認用" in build_site.SITE_PATH.read_text(encoding="utf-8"))
        finally:
            C.DB_PATH, C.ICS_PATH, build_site.SITE_PATH = orig


# ------------------------------------------- 実データで見つかった不具合の再発防止
def test_real_world_regressions() -> None:
    """実際にTonamelから取れたデータで起きた誤りを、二度と起こさないための確認。"""
    print("\n[14] 実データで見つかった不具合")
    from src import config as C
    from src.normalize import detect_by_address_shape, detect_prefecture, normalize
    from src.scrape import _needs_detail, extract_address

    # --- ① 会場の住所が「京都千代田区」と誤記されていた（東の字が抜けている）---
    # 短縮形「京都」を先に見ていたため京都府と判定していた。
    # 市区町村名を先に見ることで東京都と判定できる。
    typo = "カードショップおうち秋葉原店\n京都千代田区外神田４丁目７−１ リバティ11号館 5階"
    check("誤記された住所でも区名で判定できる", detect_prefecture(typo), "東京都")
    check("正しい京都の住所は京都府のまま",
          detect_prefecture("京都府京都市中京区四条烏丸"), "京都府")
    check("東京都の住所はそのまま", detect_prefecture("東京都千代田区外神田"), "東京都")

    # --- ② 大会結果に出てくるチーム名を地名と取り違えていた ---
    # 「町田サイファー」というチーム名から東京都と判定してしまっていた。
    results_page = (
        "決勝トーナメント\n主催：\nnanacs\nイベント結果\n"
        "3位 高大社\n予選1位　TNT愛好会\n2位　町田サイファー\nしらすぅ\n"
        "開催形式\nオフライン\n"
    )
    c = normalize(Competition(id="r1", url="u", title="決勝トーナメント",
                              format="オフライン", raw_text=results_page))
    check("チーム名を地名と取り違えない", c.prefecture, "")

    # --- ③ 一覧カードに住所がラベル無しで載っている ---
    card = ("募集前\n第3回　強奪の宴杯　カートン争奪\n2026/11/07(土)\n"
            "愛知県名古屋市中村区椿町13-4スパーク椿町6F\n¥ 2,500\n0/64\n")
    check("ラベル無しの住所行を拾う",
          extract_address(card), "愛知県名古屋市中村区椿町13-4スパーク椿町6F")
    check("住所の形から判定できる", detect_by_address_shape(card), "愛知県")
    c = normalize(Competition(id="r2", url="u", format="オフライン", raw_text=card))
    check("一覧だけでも都道府県が入る", c.prefecture, "愛知県")

    # --- ④ 説明文が長いと「開催場所」欄が1500字で切り捨てられていた ---
    # 住所は切る前に取り出して address に持たせる。
    long_page = (
        "はっちcs 3人チーム戦 in 大さん橋ホール\n主催：\nはっちcs\n"
        "開催形式\nオフライン\nイベント詳細\n"
        + "本大会の注意事項がここに延々と書かれています。" * 90 + "\n"
        + "続きを読む\n開催場所\n大さん橋ホール\n"
          "神奈川県横浜市中区海岸通1-1-4\n連絡先\nx.com/example\n"
    )
    check_true("テスト文が1500字を超えている", len(long_page) > 1500)
    addr = extract_address(long_page, "大さん橋ホール")
    check("切り捨てより後ろにある住所を拾える", addr, "神奈川県横浜市中区海岸通1-1-4")
    check("会場名そのものは住所に含めない", "大さん橋ホール" in addr, False)
    check("次の項目（連絡先）を巻き込まない", "連絡先" in addr, False)

    comp = Competition(id="r3", url="u", format="オフライン", venue="大さん橋ホール")
    comp.address = addr
    comp.raw_text = long_page[:1500]      # 保存されるのは切られたぶんだけ
    normalize(comp)
    check("住所から都道府県が入る", comp.prefecture, "神奈川県")
    check("地方も入る", comp.region, "関東")

    # --- ⑤ 郵便番号だけが手がかりの場合 ---
    postal = "会場\nカードショップ例\n〒060-0061 北海道札幌市中央区南一条西\n"
    check("郵便番号のある行を住所として拾う",
          detect_prefecture(extract_address(postal, "カードショップ例")), "北海道")

    # --- ⑥ 紛らわしい地名 ---
    check("浜松町は東京（浜松＝静岡と混同しない）",
          detect_prefecture("東京都立産業貿易センター浜松町館"), "東京都")
    check("浜松町だけでも東京", detect_prefecture("浜松町館"), "東京都")
    check("浜松は静岡のまま", detect_prefecture("浜松の会場"), "静岡県")
    check("『栄光カップ』を名古屋の栄と誤認しない", detect_prefecture("栄光カップ"), None)
    check("会場名だけで手がかりが無ければ空", detect_prefecture("サンモール店"), None)

    # --- ⑦ 説明文の中の関係ない地名を拾わない ---
    noisy = ("イベント詳細\n次回は大阪でも開催予定です。\n"
             "過去の優勝者は福岡出身。\n開催場所\nカードショップ例\n東京都新宿区西新宿\n")
    c = normalize(Competition(id="r4", url="u", format="オフライン", raw_text=noisy))
    check("説明文の雑談ではなく開催場所を見る", c.prefecture, "東京都")

    # --- ⑧ 詳細ページの取り直し ---
    fresh = Competition(id="k1", url="u", title="既存の大会", start_date="2026-09-01")
    old_ver = Competition.from_dict(fresh.to_dict())
    old_ver.detail_version = C.DETAIL_VERSION
    old_ver.source = "detail"
    known = {"k1": old_ver}
    check("情報が揃っていれば詳細を開き直さない",
          _needs_detail(fresh, {"k1"}, known), False)

    outdated = Competition.from_dict(old_ver.to_dict())
    outdated.detail_version = 1
    check("抽出ロジックが新しくなったら取り直す",
          _needs_detail(fresh, {"k1"}, {"k1": outdated}), True)

    api_only = Competition.from_dict(old_ver.to_dict())
    api_only.source = "api"
    check("取得上限で詳細が取れなかったものは取り直す",
          _needs_detail(fresh, {"k1"}, {"k1": api_only}), True)
    check("未知の大会は当然取りにいく",
          _needs_detail(Competition(id="new", url="u", title="新", start_date="2026-09-01"),
                        {"k1"}, known), True)

    # --- ⑨ 住所は差分検知に含めない（付け直しで通知が飛ばない） ---
    before = Competition(id="s1", url="u", title="大会", venue="会場")
    sig = before.signature()
    before.address = "東京都新宿区西新宿1-1-1"
    normalize(before)
    check("住所が入っても『変更あり』にならない", before.signature(), sig)


def main_() -> int:
    print("Xrossstars 大会ウォッチャー 自己テスト")
    test_dates()
    test_json_index()
    test_text_enrich()
    test_store()
    test_ics()
    test_fixture_run()
    test_quiet_hours()
    test_pending()
    test_quiet_end_to_end()
    test_normalize()
    test_search()
    test_build_site()
    test_pipeline_outputs()
    test_real_world_regressions()
    print("\n" + "=" * 60)
    if failures:
        print(f"❌ {len(failures)}件 失敗:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("✅ すべて成功")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
