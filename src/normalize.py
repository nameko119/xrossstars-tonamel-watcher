"""自由記述のフィールドから、検索に使える正規化データを導き出す。

Tonamelから取れるのは「大阪日本橋 カードショップABC」「定員16名」「参加費 500円」
といった人間向けの文字列なので、そのままでは「関西で」「20人以上」「無料のみ」
といった絞り込みができない。ここで次の項目を作る。

    prefecture     都道府県名（例: "東京都"）
    region         地方名（例: "関東"）
    capacity_num   定員の人数（int）
    fee_num        参加費の金額（int / 無料は0）
    is_online      オンライン開催か（True/False/None）

いずれも推定なので、確信が持てないときは埋めずにNoneのままにする。
（誤って埋めると検索から漏れるより悪い＝間違った結果が出るため）
"""

from __future__ import annotations

import re
import unicodedata

from .models import Competition

# --- 都道府県と地方 ---------------------------------------------------------
REGIONS: dict[str, tuple[str, ...]] = {
    "北海道": ("北海道",),
    "東北": ("青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"),
    "関東": ("茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"),
    "中部": ("新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
             "岐阜県", "静岡県", "愛知県"),
    "関西": ("三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"),
    "中国": ("鳥取県", "島根県", "岡山県", "広島県", "山口県"),
    "四国": ("徳島県", "香川県", "愛媛県", "高知県"),
    "九州・沖縄": ("福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
                   "鹿児島県", "沖縄県"),
}
PREFECTURES: tuple[str, ...] = tuple(p for ps in REGIONS.values() for p in ps)
PREF_TO_REGION: dict[str, str] = {
    p: region for region, ps in REGIONS.items() for p in ps
}
# 「東京」「大阪」のように接尾辞なしで書かれることが多いので、短い形も引けるようにする
SHORT_TO_PREF: dict[str, str] = {}
for _p in PREFECTURES:
    SHORT_TO_PREF[_p] = _p
    if _p != "北海道":
        SHORT_TO_PREF[re.sub(r"[都道府県]$", "", _p)] = _p

# よく会場名に出る地名 → 都道府県。
# 取り違えが起きやすい地名（「日本橋」は東京にも大阪にもある）は意図的に入れていない。
CITY_TO_PREF: dict[str, str] = {
    "札幌": "北海道", "すすきの": "北海道",
    "仙台": "宮城県", "青葉区": "宮城県",
    "秋葉原": "東京都", "アキバ": "東京都", "新宿": "東京都", "池袋": "東京都",
    "渋谷": "東京都", "中野": "東京都", "秋葉": "東京都", "立川": "東京都",
    "町田": "東京都", "上野": "東京都", "神田": "東京都", "高田馬場": "東京都",
    "錦糸町": "東京都", "蒲田": "東京都", "吉祥寺": "東京都",
    "横浜": "神奈川県", "川崎": "神奈川県", "藤沢": "神奈川県", "相模原": "神奈川県",
    "大宮": "埼玉県", "さいたま": "埼玉県", "川口": "埼玉県", "所沢": "埼玉県",
    "船橋": "千葉県", "柏": "千葉県", "津田沼": "千葉県", "海浜幕張": "千葉県",
    "名古屋": "愛知県", "栄": "愛知県", "大須": "愛知県", "金山": "愛知県",
    "梅田": "大阪府", "難波": "大阪府", "なんば": "大阪府", "心斎橋": "大阪府",
    "天王寺": "大阪府", "日本橋筋": "大阪府", "堺": "大阪府",
    "三宮": "兵庫県", "神戸": "兵庫県", "姫路": "兵庫県",
    "河原町": "京都府", "四条": "京都府",
    "博多": "福岡県", "天神": "福岡県", "小倉": "福岡県",
    "那覇": "沖縄県", "国際通り": "沖縄県",
    "広島市": "広島県", "岡山市": "岡山県", "松山市": "愛媛県", "高松": "香川県",
    "新潟市": "新潟県", "静岡市": "静岡県", "浜松": "静岡県", "宇都宮": "栃木県",
    "高崎": "群馬県", "水戸": "茨城県", "鹿児島市": "鹿児島県", "熊本市": "熊本県",
}

ONLINE_WORDS = ("オンライン", "online", "リモート", "web開催", "ウェブ開催", "配信")
OFFLINE_WORDS = ("オフライン", "offline", "現地", "店舗", "会場", "対面")

# --- 数値の抽出 -------------------------------------------------------------
_NUM = r"(\d{1,6}(?:,\d{3})*)"
_CAPACITY_RE = re.compile(_NUM + r"\s*(?:名|人|チーム|組|pt|Pt)")
_FEE_RE = re.compile(_NUM + r"\s*(?:円|yen|JPY)", re.IGNORECASE)
_FREE_WORDS = ("無料", "0円", "０円", "free", "参加費なし", "参加費無し")
_UNLIMITED_WORDS = ("無制限", "上限なし", "制限なし", "定員なし")


def _han(text: str) -> str:
    """全角英数字を半角に揃える。"""
    return unicodedata.normalize("NFKC", text or "")


def parse_count(text: str) -> int | None:
    """「32名」「16人」「定員 8チーム」→ 数値。分からなければNone。"""
    t = _han(text)
    if not t:
        return None
    if any(w in t for w in _UNLIMITED_WORDS):
        return None
    m = _CAPACITY_RE.search(t)
    if m:
        return int(m.group(1).replace(",", ""))
    # 単位が無くても、数字だけなら人数とみなす（「定員: 32」など）
    m = re.fullmatch(r"\s*" + _NUM + r"\s*", t)
    if m:
        n = int(m.group(1).replace(",", ""))
        return n if 1 <= n <= 100_000 else None
    return None


def parse_fee(text: str) -> int | None:
    """「1000円」「無料」→ 金額。分からなければNone。"""
    t = _han(text)
    if not t:
        return None
    low = t.lower()
    m = _FEE_RE.search(t)
    if m:
        return int(m.group(1).replace(",", ""))
    if any(w in low for w in _FREE_WORDS):
        return 0
    m = re.fullmatch(r"\s*" + _NUM + r"\s*", t)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def detect_prefecture(*texts: str) -> str | None:
    """会場名などから都道府県を推定する。"""
    blob = " ".join(_han(t) for t in texts if t)
    if not blob:
        return None
    # 「〜県」「〜都」まで書かれていれば確実なので最優先
    for pref in PREFECTURES:
        if pref in blob:
            return pref
    # 次に「東京」「大阪」など接尾辞なしの表記
    for short, pref in sorted(SHORT_TO_PREF.items(), key=lambda kv: -len(kv[0])):
        if len(short) >= 2 and short in blob:
            return pref
    # 最後に地名から推定。1文字の地名は誤爆する（「栄光杯」の「栄」など）ので使わない
    for city, pref in sorted(CITY_TO_PREF.items(), key=lambda kv: -len(kv[0])):
        if len(city) >= 2 and city in blob:
            return pref
    return None


def detect_online(*texts: str, existing: str = "") -> bool | None:
    if existing == "オンライン":
        return True
    if existing == "オフライン":
        return False
    blob = " ".join(_han(t) for t in texts if t).lower()
    if not blob:
        return None
    has_on = any(w.lower() in blob for w in ONLINE_WORDS)
    has_off = any(w.lower() in blob for w in OFFLINE_WORDS)
    if has_on and not has_off:
        return True
    if has_off and not has_on:
        return False
    return None


def normalize(comp: Competition) -> Competition:
    """派生フィールドを埋める。元のフィールドは書き換えない。

    差分検知の signature() には派生フィールドを含めていないので、
    ここで値が入っても「変更あり」通知は発生しない。
    """
    comp.capacity_num = parse_count(comp.capacity)
    comp.fee_num = parse_fee(comp.entry_fee)

    online = detect_online(comp.format, comp.venue, comp.raw_text, existing=comp.format)
    comp.is_online = online
    if online is True:
        # オンライン開催に都道府県は無い。形式(is_online)で絞ってもらう
        comp.prefecture = ""
        comp.region = ""
    else:
        pref = detect_prefecture(comp.venue, comp.title, comp.raw_text)
        comp.prefecture = pref or ""
        comp.region = PREF_TO_REGION.get(pref or "", "")
    return comp


def normalize_all(competitions) -> None:
    for comp in competitions:
        normalize(comp)
