"""大会データのモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Competition:
    """1つの大会。全フィールドJSONシリアライズ可能な型のみ。"""

    id: str  # tonamel.com/competition/<id> の <id>
    url: str
    title: str = ""
    # ISO8601文字列（タイムゾーン付き）。不明ならNone
    start_at: str | None = None
    end_at: str | None = None
    # 時刻不明で日付だけ分かっている場合 "YYYY-MM-DD"
    start_date: str | None = None
    # "オンライン" / "オフライン" / "" （不明）
    format: str = ""
    venue: str = ""  # 会場名（例: "カードショップおうち秋葉原店"）
    # 会場の住所。詳細ページの「開催場所」欄から取る。
    # raw_text は途中で切るので、住所だけは別に持っておかないと失われる。
    address: str = ""
    organizer: str = ""
    entry_fee: str = ""
    capacity: str = ""
    entry_period: str = ""
    image_url: str = ""
    # --- 検索用の正規化フィールド（src/normalize.py が自動で埋める） ---------
    # 自由記述から推定した値。確信が持てないときは空 / None のままにする。
    # 差分検知(signature)には含めないので、ここが埋まっても「変更」通知は出ない。
    prefecture: str = ""          # 例: "東京都"
    region: str = ""              # 例: "関東"
    capacity_num: int | None = None   # 定員の人数
    fee_num: int | None = None        # 参加費（無料は0）
    is_online: bool | None = None     # オンライン開催か

    # 取得元と生テキスト（デバッグ・後からの再パース用）
    source: str = "list"
    # 詳細ページを取ったときの抽出ロジックの版。
    # config.DETAIL_VERSION より古い大会は、次の実行で詳細を取り直す。
    detail_version: int = 0
    raw_text: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)
    # 内部管理用
    first_seen: str = ""
    last_updated: str = ""
    seq: int = 0  # ICSのSEQUENCE。内容が変わるたびに+1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Competition":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    # --- 変更検知に使う「本質的な中身」 -------------------------------------
    def signature(self) -> tuple:
        return (
            self.title.strip(),
            self.start_at or "",
            self.end_at or "",
            self.start_date or "",
            self.format.strip(),
            self.venue.strip(),
            self.entry_fee.strip(),
            self.capacity.strip(),
            self.organizer.strip(),
        )

    def merge_from(self, other: "Competition") -> "Competition":
        """otherの非空フィールドで自分を上書きした新しいオブジェクトを返す。"""
        merged = Competition.from_dict(self.to_dict())
        for key in (
            "url",
            "title",
            "start_at",
            "end_at",
            "start_date",
            "format",
            "venue",
            "address",
            "organizer",
            "entry_fee",
            "capacity",
            "entry_period",
            "image_url",
            "raw_text",
        ):
            val = getattr(other, key)
            if val:
                setattr(merged, key, val)
        if other.raw_json:
            merged.raw_json = other.raw_json
        if other.source and other.source != "list":
            merged.source = other.source
        if other.detail_version:
            merged.detail_version = other.detail_version
        return merged
