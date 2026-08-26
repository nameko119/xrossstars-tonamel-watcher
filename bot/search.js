/**
 * 大会の絞り込みロジック（JavaScript版）。
 *
 * このファイルは Web ページ（docs/index.html）と Discord bot（Cloudflare Worker）の
 * 両方に、そのまま連結して埋め込まれる。import / export を使っていないのはそのため。
 *
 * Python版（src/search.py）と同じ結果になるよう作ってあり、
 * tests/test_parity.js で両者の結果が一致することを確認している。
 * 片方だけ直すとズレるので、条件を変えるときは必ず両方直すこと。
 */
const XSSearch = (() => {
  "use strict";

  const REGIONS = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"],
    "関西": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
  };
  const PREFECTURES = Object.values(REGIONS).flat();
  const SHORT_TO_PREF = {};
  for (const p of PREFECTURES) {
    SHORT_TO_PREF[p] = p;
    if (p !== "北海道") SHORT_TO_PREF[p.replace(/[都道府県]$/, "")] = p;
  }

  /** 比較用に文字列をならす（全角/半角・大文字小文字・連続空白を吸収）。 */
  function fold(text) {
    if (!text) return "";
    return String(text).normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
  }

  /** 開催日を "YYYY-MM-DD" で返す。分からなければ null。 */
  function eventDate(c) {
    if (c.start_at) {
      const m = String(c.start_at).match(/^(\d{4}-\d{2}-\d{2})/);
      if (m) return m[1];
    }
    if (c.start_date && /^\d{4}-\d{2}-\d{2}$/.test(c.start_date)) return c.start_date;
    return null;
  }

  function searchableText(c) {
    return fold([c.title, c.venue, c.address, c.organizer, c.prefecture, c.region,
      c.format, c.id].filter(Boolean).join(" "));
  }

  function resolvePrefecture(name) {
    const n = fold(name).replace(/ /g, "");
    for (const [short, pref] of Object.entries(SHORT_TO_PREF)) {
      if (fold(short) === n) return pref;
    }
    return name;
  }

  /**
   * 1件が条件に合うか。
   * q は src/search.py の Query と同じ形の素のオブジェクト。
   */
  function matches(c, q, today) {
    const d = eventDate(c);

    if (d === null) {
      if (q.include_undated === false) return false;
      if (q.date_from || q.date_to) return false;   // 期間指定時は日付不明を除く
    } else {
      if (!q.include_past && d < today) return false;
      if (q.date_from && d < q.date_from) return false;
      if (q.date_to && d > q.date_to) return false;
    }

    if (q.online === true || q.online === false) {
      if (c.is_online !== q.online) return false;
    }

    if (q.prefectures && q.prefectures.length) {
      const wanted = q.prefectures.map(resolvePrefecture);
      if (!wanted.includes(c.prefecture)) return false;
    }
    if (q.region && c.region !== q.region) return false;

    if (q.capacity_min != null) {
      if (c.capacity_num == null || c.capacity_num < q.capacity_min) return false;
    }
    if (q.capacity_max != null) {
      if (c.capacity_num == null || c.capacity_num > q.capacity_max) return false;
    }
    if (q.fee_max != null) {
      if (c.fee_num == null || c.fee_num > q.fee_max) return false;
    }
    if (q.organizer && !fold(c.organizer).includes(fold(q.organizer))) return false;

    if (q.text) {
      const hay = searchableText(c);
      for (const word of fold(q.text).split(" ")) {
        if (word && !hay.includes(word)) return false;
      }
    }
    return true;
  }

  const FAR_FUTURE = "9999-12-31";
  const FAR_PAST = "0000-01-01";

  function compare(a, b, mode) {
    if (mode === "title") {
      const ta = fold(a.title), tb = fold(b.title);
      if (ta !== tb) return ta < tb ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    if (mode === "added") {
      const aa = a.first_seen || "", bb = b.first_seen || "";
      if (aa !== bb) return aa < bb ? -1 : 1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    const far = mode === "-date" ? FAR_PAST : FAR_FUTURE;
    const da = eventDate(a) || far, db = eventDate(b) || far;
    if (da !== db) return da < db ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  }

  /** 条件に合う大会を並べ替えて返す。limit/offset は 0 で無制限。 */
  function search(competitions, q, today) {
    q = q || {};
    today = today || new Date().toISOString().slice(0, 10);
    let hits = competitions.filter((c) => matches(c, q, today));
    const mode = q.sort || "date";
    hits.sort((a, b) => compare(a, b, mode));
    if (mode === "-date") hits.reverse();
    if (q.offset) hits = hits.slice(q.offset);
    if (q.limit) hits = hits.slice(0, q.limit);
    return hits;
  }

  function count(competitions, q, today) {
    today = today || new Date().toISOString().slice(0, 10);
    return competitions.filter((c) => matches(c, q || {}, today)).length;
  }

  // --- 期間の近道指定 ------------------------------------------------------
  function ymd(date) {
    return date.toISOString().slice(0, 10);
  }
  function addDays(iso, days) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + days);
    return ymd(d);
  }
  function weekday(iso) {          // 月曜=0 … 日曜=6
    return (new Date(iso + "T00:00:00Z").getUTCDay() + 6) % 7;
  }

  const PERIOD_CHOICES = ["今日", "明日", "今週末", "今週", "来週", "今月", "来月", "30日以内"];

  /** 「今週末」などを [date_from, date_to] に変換する。該当なしは ["", ""]。 */
  function periodRange(name, today) {
    today = today || ymd(new Date());
    const firstOfMonth = today.slice(0, 8) + "01";
    const nextMonthFirst = (() => {
      const d = new Date(firstOfMonth + "T00:00:00Z");
      d.setUTCMonth(d.getUTCMonth() + 1);
      return ymd(d);
    })();
    switch (name) {
      case "今日": case "today":
        return [today, today];
      case "明日": case "tomorrow": {
        const d = addDays(today, 1);
        return [d, d];
      }
      case "今週末": case "週末": case "weekend": {
        const sat = addDays(today, (5 - weekday(today) + 7) % 7);
        return [sat, addDays(sat, 1)];
      }
      case "今週": case "week": {
        const mon = addDays(today, -weekday(today));
        return [mon > today ? mon : today, addDays(mon, 6)];
      }
      case "来週": case "next_week": {
        const mon = addDays(today, -weekday(today) + 7);
        return [mon, addDays(mon, 6)];
      }
      case "今月": case "month":
        return [firstOfMonth > today ? firstOfMonth : today, addDays(nextMonthFirst, -1)];
      case "来月": case "next_month": {
        const d = new Date(nextMonthFirst + "T00:00:00Z");
        d.setUTCMonth(d.getUTCMonth() + 1);
        return [nextMonthFirst, addDays(ymd(d), -1)];
      }
      case "30日以内": case "30days":
        return [today, addDays(today, 30)];
      default:
        return ["", ""];
    }
  }

  return {
    REGIONS, PREFECTURES, PERIOD_CHOICES,
    fold, eventDate, searchableText, resolvePrefecture,
    matches, search, count, periodRange, addDays,
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = XSSearch;
