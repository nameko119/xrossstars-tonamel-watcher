# Xrossstars 大会ウォッチャー（Tonamel）

Tonamel に掲載される **Xrossstars（クロススターズ）の大会**を3時間おきに自動チェックし、

- 新着があれば **Discord に通知**
- 全大会を **`.ics` カレンダー**にして **Google カレンダーで購読**

できるようにする、個人利用の仕組みです。GitHub Actions の無料枠だけで動きます。

さらに、集めた大会を

- **Webページ**（GitHub Pages）で一覧・検索
- **Discord bot** の `/一覧` `/検索` で絞り込み

できます。

> **はじめてセットアップする方へ**
>
> 1. [`SETUP.md`](SETUP.md) … 通知とカレンダーまで（まずこちら）
> 2. [`BOT_SETUP.md`](BOT_SETUP.md) … Webページと Discord bot

---

## しくみ

```
GitHub Actions（3時間おき / cron）
        │
        ▼
Playwright + Chromium で tonamel.com/competitions?game=XrossStars&region=JP を開く
        │  ページが裏で叩く API(JSON) を横取り ─┐
        │  JSON-LD を読む ───────────────────┤ 良い情報を優先採用
        │  描画後の DOM テキストを解析 ───────┘
        ▼
data/known_competitions.json と突き合わせて差分検知
        │
        ├─ 新着/変更あり ─┬─ 昼間(8〜23時) → Discord Webhook へ通知
        │                 └─ 夜間(23〜8時) → 保留し、朝8時台の実行でまとめて通知
        ├─ data/calendar.ics を再生成（夜間も更新する）
        └─ docs/index.html を再生成（一覧・検索ページ）
                │
                ▼
        Discord bot（Cloudflare Worker）は
        data/known_competitions.json を直接読んで /一覧 /検索 に答える
                │
                ▼
        リポジトリへ自動コミット
                │
                ▼
        Google カレンダーが raw URL を購読して自動更新
```

## なぜスクレイピングなのか

Tonamel の大会一覧は Vue 系の SPA で、HTML には大会データが入っていません
（`curl` で取得しても meta タグしか返ってきません）。そのためヘッドレスブラウザで
実際にページを描画してから読み取っています。

セレクタ変更に耐えられるよう、**API レスポンスの横取り → JSON-LD → DOM テキスト**の
3系統から情報を取り、取れたものを優先度順にマージしています。

## ファイル構成

| パス | 役割 |
|---|---|
| `src/scrape.py` | Playwright での取得。API横取り・JSON-LD・DOM解析 |
| `src/dateparse.py` | 「2026年9月5日(土) 13:00」「9/5 13:00〜18:00」等の表記ゆれを吸収 |
| `src/store.py` | 大会DBの読み書き、差分検知（新規 / 変更）、夜間の通知保留 |
| `src/quiet.py` | 静音時間帯（夜間は通知しない）の判定 |
| `src/notify_discord.py` | Discord Webhook 通知（embed・レート制限対応） |
| `src/build_ics.py` | `.ics` 生成（RFC5545準拠・75オクテット折り返し） |
| `src/normalize.py` | 会場名→都道府県、「32名」→32 など、検索できる形への変換 |
| `src/search.py` | 一覧・検索の条件判定（Python側） |
| `src/build_site.py` | `docs/index.html`（一覧・検索ページ）の生成 |
| `src/build_bot.py` | Cloudflareに貼る `bot/worker.bundle.js` の生成 |
| `src/cli.py` | 手元で一覧・検索するコマンド |
| `src/main.py` | 一連の実行 |
| `src/config.py` | 設定値（環境変数で上書き可） |
| `bot/search.js` | 検索ロジックのJS版。**Webページとbotが共有** |
| `bot/worker.js` | Discord bot本体（Cloudflare Worker） |
| `bot/commands.json` | スラッシュコマンドの定義 |
| `docs/index.html` | 生成される一覧・検索ページ（GitHub Pagesで公開） |
| `data/known_competitions.json` | 既知の大会DB。**手で消さないでください**（消すと全件が新着になります） |
| `data/calendar.ics` | 生成されるカレンダー。Googleが購読する先 |
| `.github/workflows/watch.yml` | 定期実行の設定 |
| `tests/` | ネットに出ずに動く自己テスト |

## 手元で動かす

```bash
pip install -r requirements.txt
python -m playwright install chromium

python -m tests.test_all       # ロジックの自己テスト（ネット不要）
python -m tests.test_browser   # Chromium込みの動作確認（ネット不要）
python -m tests.test_parity    # JS版の検索がPython版と一致するか（要Node.js）
python -m tests.test_bot       # Discord botの署名検証と応答（要Node.js）

python -m src.main --dry-run --no-detail   # 保存も通知もせず取得結果だけ表示
python -m src.main --debug                 # debug/ に画面キャプチャとAPIログを出す

python -m src.build_bot                    # bot/worker.bundle.js を作り直す
```

集めた大会は手元でも引けます。

```bash
python -m src.cli list                          # 今後の大会をすべて表示
python -m src.cli search 初心者                  # キーワード検索
python -m src.cli search --pref 東京 --free      # 東京 かつ 無料
python -m src.cli search --period 今週末 --offline
python -m src.cli search --min-cap 16 --max-fee 1000 --json
```

主なオプション:

| オプション | 効果 |
|---|---|
| `--dry-run` | DBもICSも書き換えず、通知もしない |
| `--no-detail` | 大会詳細ページを開かない（速い） |
| `--no-discord` | Discord通知だけ止める |
| `--debug` | `debug/` にスクリーンショット・HTML・API通信ログを保存 |
| `--fixture path.json` | ネットに出ずJSONから読み込む |
| `--ignore-quiet` | 静音時間帯でも保留せずすぐ通知する |

## 設定（環境変数）

`src/config.py` の既定値は環境変数で上書きできます。よく使うもの:

| 変数 | 既定 | 説明 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | （空） | 未設定なら通知をスキップします |
| `FETCH_DETAIL` | `1` | `0` で詳細ページを開かない |
| `MAX_DETAIL_FETCH` | `40` | 1回の実行で開く詳細ページの上限 |
| `NOTIFY_ON_CHANGE` | `1` | `0` にすると新着のみ通知（日時変更は通知しない） |
| `QUIET_HOURS_ENABLED` | `1` | `0` で夜間の通知抑制をやめる（24時間いつでも通知） |
| `QUIET_HOURS_START` | `23` | 静音を始める時刻（JSTの「時」） |
| `QUIET_HOURS_END` | `8` | 静音を終える時刻（JSTの「時」） |
| `ICS_KEEP_PAST_DAYS` | `180` | これより古い大会はICSから落とす |
| `DEFAULT_DURATION_HOURS` | `4` | 終了時刻不明のときの予定の長さ |
| `SCRAPER_DEBUG` | `0` | `1` でデバッグ出力 |

## 夜間の通知抑制について

**23時〜翌8時（JST）は Discord へ通知しません。** ただし止まるのは通知だけで、
**取得・DB更新・カレンダー生成は夜間も通常どおり動きます。**

夜のあいだに見つかった大会は「あとで送るリスト」（`data/known_competitions.json` の
`meta.pending`）に積まれ、静音時間が明けた最初の実行 = **朝8時10分ごろの実行で
「🌙 夜間にみつかった分のまとめ」として1通に束ねて届きます。**

細かい挙動:

- 保留するのは**大会IDだけ**です。送信時にDBから最新の内容を引き直すので、
  夜のうちに日時が変わっても、朝には正しい情報が届きます。
- 同じ大会を二重には積みません。「新着」として保留中の大会に変更があっても、
  新着通知1件にまとまります。
- **送信に失敗したら保留は消しません。** 次の実行で再送します。
- **手動実行（Run workflow）では夜間でもすぐ通知します。** 動作確認のためです。
  夜間の挙動そのものを確かめたいときは `respect_quiet` にチェックを入れてください。
- 実行が失敗したときのエラー通知も、夜間は鳴らしません。

時間帯を変えたい場合は `.github/workflows/watch.yml` の `QUIET_HOURS_START` /
`QUIET_HOURS_END` を書き換えてください（`QUIET_HOURS_ENABLED: "0"` で無効化）。
cron の並びも、静音明け直後に1回走るようにしておくと朝一番で受け取れます。

## 検索できる項目と、その作られ方

Tonamelから取れるのは「大阪府大阪市 なんばカードスペース」「定員16名」「参加費 500円」
といった**人間向けの文字列**です。そのままでは絞り込めないので、
`src/normalize.py` が毎回すべての大会に対して次の項目を推定して付け直します。

| 項目 | 例 | 作り方 |
|---|---|---|
| `address` | `東京都千代田区外神田4-7-1` | 詳細ページの「開催場所」欄から。判定の主な手がかり |
| `prefecture` | `大阪府` | 住所・会場名から。略称や「秋葉原」「天神」などの地名にも対応 |
| `region` | `関西` | 都道府県から機械的に |
| `capacity_num` | `16` | 「16名」「24チーム」「１６人」から。「無制限」は空 |
| `fee_num` | `500` | 「500円」「1,500円」から。「無料」は `0` |
| `is_online` | `false` | 開催形式や会場の記載から |

**推定できないときは空のままにします。** 間違った値を入れて誤った検索結果を出すより、
その条件に引っかからないほうがマシだからです。会場の記載が「調整中」だけの大会は
地域では絞れませんが、キーワード検索には出てきます。

判定ルールを直すと、**過去に取得済みの大会にも遡って効きます**（毎回付け直しているため）。
なお、これらの項目は差分検知の対象外なので、付け直しで「変更あり」通知が飛ぶことはありません。

### 都道府県を当てるときの順番

説明文を丸ごと都道府県名で検索すると、関係のない土地の話を拾ってしまいます
（実際に、大会結果に出てきたチーム名「町田サイファー」から東京都と誤判定していました）。
そのため、確かな手がかりから順に見て、見つかった時点で打ち切ります。

1. **住所 (`address`) と会場名** … いちばん確か
2. **大会名** … 「大阪◯◯杯」など
3. **説明文の中で住所の形をしている部分** … 「愛知県名古屋市…」のように
   都道府県名のすぐ後ろに市区郡町村が続くもの
4. **「開催場所」欄や郵便番号のまわり** … ここでは「東京」「大阪」のような
   接尾辞なしの略称は使わない

それぞれの中でも **① 都道府県名 → ② 市区町村名 → ③ 略称** の順に見ます。
②を③より先に見るのが要点で、たとえばTonamelに
`京都千代田区外神田…`（「東」が抜けた誤記）と登録されている会場があっても、
「千代田区」を先に拾うので東京都と判定できます。

地名の辞書には**日本にひとつしか無い名前だけ**を入れています。
「中央区」「北区」「府中市」のように複数の県にあるものや、
「栄」「柏」のような1文字の地名は、取り違えるので入れていません。

### 詳細ページの取り直し

抽出のしかたを直したときは、`src/config.py` の `DETAIL_VERSION` を1つ上げてください。
次の実行で、既存の大会も**1回だけ**詳細ページを取り直して情報を入れ直します
（毎回取り直すことはありません）。前回の実行で取得件数の上限に当たって
詳細が取れなかった大会も、同じ仕組みで自動的に拾い直します。

## 検索ロジックは1か所にまとめてある

同じ条件で違う結果が出ないよう、判定は次の2ファイルだけに置いています。

- `src/search.py` … Python版（CLI・テスト用）
- `bot/search.js` … JS版（**Webページとbotが両方これを使う**）

`tests/test_parity.py` が、31通りの条件で**両者の結果が完全に一致すること**を毎回確認します。
条件を変えるときは必ず両方を直してください（片方だけ直すとテストが落ちます）。

## 気をつけること

- **初回実行では個別通知しません。** DBが空のときは「現在N件を初期登録しました」という
  まとめ1通だけ送ります。掲載中の大会が全部通知されて埋まるのを防ぐためです。
- **`data/known_competitions.json` を消すと**次の実行が初回扱いになり、また全件が
  初期登録されます（通知は1通だけなので実害は小さいです）。
- 一覧から消えた大会（終了した大会）はDBに残します。ICSからは
  `ICS_KEEP_PAST_DAYS` 日を過ぎたら自動的に落ちます。
- Tonamel への負荷を避けるため、詳細ページは1.5秒間隔で開き、1回あたり40件までにしています。
- 大会情報の正確な内容は必ず Tonamel の大会ページで確認してください。
  自動抽出のため、まれに日時や会場を取り違える可能性があります。
