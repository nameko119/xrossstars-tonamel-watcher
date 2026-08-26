"""大会DB（JSONファイル）の読み書きと差分検知。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config as C
from .models import Competition

SCHEMA_VERSION = 1


@dataclass
class Diff:
    new: list[Competition] = field(default_factory=list)
    changed: list[tuple[Competition, Competition]] = field(default_factory=list)  # (旧, 新)
    unchanged: int = 0
    is_seed: bool = False  # 初回（DBが空）だったか

    @property
    def has_updates(self) -> bool:
        return bool(self.new or self.changed)


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or C.DB_PATH
        self.competitions: dict[str, Competition] = {}
        self.meta: dict = {}
        self.load()

    # --- 入出力 ------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            self.competitions, self.meta = {}, {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            # 壊れていたら退避して作り直す（通知の暴発を防ぐため中身は残す）
            self.path.rename(self.path.with_suffix(".broken.json"))
            self.competitions, self.meta = {}, {}
            return
        self.meta = raw.get("meta", {})
        comps = raw.get("competitions", {})
        if isinstance(comps, list):  # 旧形式への保険
            comps = {c["id"]: c for c in comps if isinstance(c, dict) and c.get("id")}
        self.competitions = {
            cid: Competition.from_dict(d) for cid, d in comps.items() if isinstance(d, dict)
        }

    def save(self, run_meta: dict | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        meta = dict(self.meta or {})
        # 計算した値で必ず上書きする（順番を逆にすると last_run が古いまま残る）
        meta.update({
            "schema_version": SCHEMA_VERSION,
            "last_run": datetime.now(C.JST).isoformat(),
            "count": len(self.competitions),
        })
        if run_meta:
            meta["last_run_info"] = run_meta
        payload = {
            "meta": meta,
            # 並べ替えて差分を安定させる（gitのdiffを読みやすくするため）
            "competitions": {
                cid: self.competitions[cid].to_dict()
                for cid in sorted(self.competitions, key=self._sort_key)
            },
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    def _sort_key(self, cid: str) -> tuple:
        c = self.competitions[cid]
        return (c.start_at or c.start_date or "9999", cid)

    @property
    def is_empty(self) -> bool:
        return not self.competitions

    # --- 差分検知 ----------------------------------------------------------
    def apply(self, scraped: list[Competition]) -> Diff:
        """取得結果をDBに反映し、差分を返す。

        - 未知のIDは「新規」
        - 既知でも日時・会場・タイトル等が変わっていれば「変更」
        - 一覧から消えた大会はDBに残す（終了した大会の履歴として保持）
        """
        now_iso = datetime.now(C.JST).isoformat()
        diff = Diff(is_seed=self.is_empty)

        for comp in scraped:
            old = self.competitions.get(comp.id)
            if old is None:
                comp.first_seen = now_iso
                comp.last_updated = now_iso
                comp.seq = 0
                self.competitions[comp.id] = comp
                diff.new.append(comp)
                continue

            merged = old.merge_from(comp)
            merged.first_seen = old.first_seen or now_iso
            merged.last_updated = now_iso
            if merged.signature() != old.signature():
                merged.seq = (old.seq or 0) + 1
                self.competitions[comp.id] = merged
                diff.changed.append((old, merged))
            else:
                merged.seq = old.seq
                self.competitions[comp.id] = merged
                diff.unchanged += 1

        return diff

    def all(self) -> list[Competition]:
        return [self.competitions[cid] for cid in sorted(self.competitions, key=self._sort_key)]

    # --- 静音時間帯の通知保留 ----------------------------------------------
    # 夜間に見つかった分は「あとで送るリスト」に積み、明けた実行でまとめて送る。
    # 大会の中身そのものは持たず、IDだけを覚えておいて送信時にDBから引き直す。
    # こうすると、保留中に日時が変わっても最新の内容で通知できる。

    MAX_PENDING = 200

    def _pending(self) -> dict:
        p = self.meta.get("pending")
        if not isinstance(p, dict):
            p = {}
        return {
            "seed": p.get("seed") if isinstance(p.get("seed"), int) else None,
            "new": [x for x in p.get("new", []) if isinstance(x, str)],
            "changed": [
                x for x in p.get("changed", [])
                if isinstance(x, dict) and isinstance(x.get("id"), str)
            ],
        }

    @property
    def has_pending(self) -> bool:
        p = self._pending()
        return bool(p["seed"] is not None or p["new"] or p["changed"])

    def defer(self, new_ids: list[str], changed: list[tuple[str, str]],
              seed_count: int | None = None) -> dict:
        """通知を保留する。changed は (大会ID, 変更内容の文面) のリスト。"""
        p = self._pending()
        if seed_count is not None:
            p["seed"] = (p["seed"] or 0) + seed_count

        already_new = set(p["new"])
        for cid in new_ids:
            if cid not in already_new:
                p["new"].append(cid)
                already_new.add(cid)

        # 「新着」として保留済みの大会は、変更を別途通知しない
        # （送信時に最新のDB内容で作るので、新着通知に変更が反映される）
        changed_ids = {c["id"] for c in p["changed"]}
        for cid, note in changed:
            if cid in already_new or cid in changed_ids:
                continue
            p["changed"].append({"id": cid, "note": note})
            changed_ids.add(cid)

        p["new"] = p["new"][-self.MAX_PENDING:]
        p["changed"] = p["changed"][-self.MAX_PENDING:]
        self.meta["pending"] = p
        return p

    def peek_pending(self) -> tuple[int | None, list[Competition], list[tuple[Competition, str]]]:
        """保留分を最新のDB内容で組み立てて返す（消さない）。

        送信が成功してから clear_pending() を呼ぶことで、
        通知に失敗したときに保留分を取りこぼさないようにしている。
        """
        p = self._pending()
        new = [self.competitions[cid] for cid in p["new"] if cid in self.competitions]
        changed = [
            (self.competitions[c["id"]], c.get("note", ""))
            for c in p["changed"] if c["id"] in self.competitions
        ]
        return p["seed"], new, changed

    def clear_pending(self) -> None:
        self.meta.pop("pending", None)

    def pending_counts(self) -> tuple[int | None, int, int]:
        p = self._pending()
        return p["seed"], len(p["new"]), len(p["changed"])
