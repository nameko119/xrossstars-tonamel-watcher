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

# 市区町村・地名 → 都道府県。
#
# ここに入れてよいのは「日本にひとつしか無い」名前だけ。
# 「中央区」「北区」「港区」「府中市」のように複数の都道府県にある名前や、
# 「栄」「柏」のような1文字の地名は、取り違えるので入れない。
# （「日本橋」も東京・大阪の両方にあるため入れていない）
CITY_TO_PREF: dict[str, str] = {
    # --- 東京23区のうち、他県と重複しないもの ---
    # 港区・中央区・北区は名古屋/大阪/京都などにもあるため除外している
    "千代田区": "東京都", "新宿区": "東京都", "文京区": "東京都", "台東区": "東京都",
    "墨田区": "東京都", "江東区": "東京都", "品川区": "東京都", "目黒区": "東京都",
    "大田区": "東京都", "世田谷区": "東京都", "渋谷区": "東京都", "中野区": "東京都",
    "杉並区": "東京都", "豊島区": "東京都", "荒川区": "東京都", "板橋区": "東京都",
    "練馬区": "東京都", "足立区": "東京都", "葛飾区": "東京都", "江戸川区": "東京都",
    # --- 政令指定都市（「市」まで含めれば一意） ---
    "札幌市": "北海道", "仙台市": "宮城県", "さいたま市": "埼玉県", "千葉市": "千葉県",
    "横浜市": "神奈川県", "川崎市": "神奈川県", "相模原市": "神奈川県",
    "新潟市": "新潟県", "静岡市": "静岡県", "浜松市": "静岡県", "名古屋市": "愛知県",
    "京都市": "京都府", "大阪市": "大阪府", "堺市": "大阪府", "神戸市": "兵庫県",
    "岡山市": "岡山県", "広島市": "広島県", "北九州市": "福岡県", "福岡市": "福岡県",
    "熊本市": "熊本県",
    # --- 県庁所在地など（「市」まで含めれば一意なものだけ） ---
    "青森市": "青森県", "盛岡市": "岩手県", "秋田市": "秋田県", "山形市": "山形県",
    "福島市": "福島県", "水戸市": "茨城県", "宇都宮市": "栃木県", "前橋市": "群馬県",
    "甲府市": "山梨県", "長野市": "長野県", "岐阜市": "岐阜県", "富山市": "富山県",
    "金沢市": "石川県", "福井市": "福井県", "大津市": "滋賀県", "奈良市": "奈良県",
    "和歌山市": "和歌山県", "鳥取市": "鳥取県", "松江市": "島根県", "山口市": "山口県",
    "徳島市": "徳島県", "高松市": "香川県", "松山市": "愛媛県", "高知市": "高知県",
    "佐賀市": "佐賀県", "長崎市": "長崎県", "大分市": "大分県", "宮崎市": "宮崎県",
    "鹿児島市": "鹿児島県", "那覇市": "沖縄県",
    # --- 会場名によく出る地名・繁華街 ---
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
    "高松": "香川県", "高崎": "群馬県", "宇都宮": "栃木県", "水戸": "茨城県",
    "浜松": "静岡県",   # 「浜松町」(東京)は長い名前が先に判定されるので誤爆しない
    # 実際の大会でよく出てくる会場・地名
    "越谷": "埼玉県", "川越駅": "埼玉県", "所沢": "埼玉県",
    "名取": "宮城県", "糸島": "福岡県", "大さん橋": "神奈川県",
    "浜松町": "東京都",   # 「浜松」(静岡)より先に判定されるよう長い名前にしてある
    "上大岡": "神奈川県", "本厚木": "神奈川県",
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


# 「住所らしい場所」を見つけるための手がかり。
# 説明文全体を都道府県名で検索すると、関係のない土地の話を拾ってしまうので、
# 説明文から探すときはこの近くだけを見る。
_ADDRESS_ANCHOR = re.compile(
    r"〒\s*\d{3}[-−]?\d{4}|(?:開催場所|開催地|会場|住所|所在地|アクセス)\s*[:：]?"
)


def address_windows(text: str, width: int = 90) -> list[str]:
    """説明文の中から「住所が書かれていそうな部分」だけを切り出す。"""
    if not text:
        return []
    out = []
    for m in _ADDRESS_ANCHOR.finditer(_han(text)):
        out.append(text[m.start(): m.start() + width])
    return out


# 「愛知県名古屋市…」のように、都道府県名のすぐ後ろに市区郡町村が続く形。
# 住所としての形をしているので、説明文の中から拾っても取り違えにくい。
# 逆に「京都千代田区」のような誤記（都道府県名が正しく書かれていない）には
# 反応しないので、そちらは市区町村名の辞書のほうで拾う。
ADDRESS_SHAPE = re.compile(
    r"(" + "|".join(PREFECTURES) + r")[^\s　]{0,8}?[市区郡町村]"
)


def detect_by_address_shape(text: str) -> str | None:
    """文章の中から「住所の形をしている部分」を見つけて都道府県を返す。"""
    if not text:
        return None
    m = ADDRESS_SHAPE.search(_han(text))
    return m.group(1) if m else None


def _by_full_name(blob: str) -> str | None:
    """「東京都」「京都府」のように接尾辞まで書かれているもの。いちばん確実。"""
    for pref in PREFECTURES:
        if pref in blob:
            return pref
    return None


def _by_city(blob: str) -> str | None:
    """市区町村・地名から。都道府県名が省略・誤記されていても効く。"""
    for city, pref in sorted(CITY_TO_PREF.items(), key=lambda kv: -len(kv[0])):
        if len(city) >= 2 and city in blob:
            return pref
    return None


def _by_short_name(blob: str) -> str | None:
    """「東京」「大阪」など接尾辞なしの表記。いちばん当てにならない。"""
    for short, pref in sorted(SHORT_TO_PREF.items(), key=lambda kv: -len(kv[0])):
        if len(short) >= 2 and short in blob:
            return pref
    return None


def detect_prefecture(*texts: str, allow_short: bool = True) -> str | None:
    """会場名・住所などから都道府県を推定する。

    確実な手がかりから順に見る。市区町村名を短縮形より先に見るのが重要で、
    たとえば住所が「京都千代田区…」と誤記されていても
    （実際にTonamel上でこう登録されている会場がある）、
    「千代田区」を先に拾うので東京都と判定できる。

    allow_short=False にすると「東京」「大阪」のような接尾辞なしの表記を
    使わなくなる。説明文のように関係ない地名が混ざる文章に対して使う。
    """
    blob = " ".join(_han(t) for t in texts if t)
    if not blob:
        return None
    found = _by_full_name(blob) or _by_city(blob)
    if found or not allow_short:
        return found
    return _by_short_name(blob)


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
        # 手がかりの確かさが高い順に見る。説明文(raw_text)を丸ごと検索すると
        # 関係のない土地の話を拾うので、住所らしい部分だけに限定する。
        pref = (
            detect_prefecture(comp.address, comp.venue)      # 住所・会場名
            or detect_prefecture(comp.title)                 # 大会名（「大阪〜杯」など）
            or detect_by_address_shape(comp.raw_text)        # 説明文中の住所らしい並び
            # 最後に「開催場所」欄や郵便番号のまわりだけを見る。
            # ここでは短縮形を使わない（説明文には他所の地名が混ざるため）
            or detect_prefecture(*address_windows(comp.raw_text), allow_short=False)
        )
        comp.prefecture = pref or ""
        comp.region = PREF_TO_REGION.get(pref or "", "")
    return comp


def normalize_all(competitions) -> None:
    for comp in competitions:
        normalize(comp)
