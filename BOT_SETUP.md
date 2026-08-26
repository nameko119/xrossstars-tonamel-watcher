# 一覧・検索を使えるようにする手順

`SETUP.md` の手順が終わって、Discordに通知が届くようになってから読んでください。
ここでは次の2つを使えるようにします。

| | 内容 | 追加で必要なもの | 所要時間 |
|---|---|---|---|
| **A. Webページ** | スマホのブラウザで一覧・検索。URLで条件を共有できる | なし | 5分 |
| **B. Discord bot** | Discord内で `/一覧` `/検索` が使える | Cloudflareアカウント、Discordアプリ | 40分 |

**Aだけでも十分使えます。** Bは手数が多いので、まずAを終わらせて、
必要になったらBに進むのがおすすめです。BはAのURLを使うので、順番は A → B です。

---

# A. Webページを公開する（GitHub Pages）

`python -m src.main` が動くたびに `docs/index.html` が作り直されているので、
GitHub Pages を有効にするだけで公開できます。

## A-1. Pages を有効にする

1. GitHubのリポジトリを開き、上部タブの **Settings** をクリック。
2. 左メニューの **Pages** をクリック。
3. **Build and deployment** の欄を次のようにします。

   | 項目 | 選ぶもの |
   |---|---|
   | Source | **Deploy from a branch** |
   | Branch | **main** |
   | フォルダ（Branchの右の欄） | **/docs** ← 重要。`/(root)` ではありません |

4. **Save** をクリック。

1〜2分すると、同じ画面の上部に

```
Your site is live at https://<ユーザー名>.github.io/xrossstars-tonamel-watcher/
```

と表示されます。**このURLを控えておいてください**（Bで使います）。

## A-2. 表示を確認する

そのURLをスマホで開いてみてください。大会が並んでいれば成功です。

- 「0件」と出る場合 → まだ大会データが入っていません。Actionsを1回手動実行してください。
- 404が出る場合 → フォルダが `/docs` になっているか、`docs/index.html` がリポジトリに
  存在するかを確認してください。

ホーム画面に追加しておくとアプリのように開けます（iPhoneは共有ボタン →「ホーム画面に追加」）。

## A-3. 使い方

- 上の **形式**（すべて／オンライン／オフライン）と **期間**（今週末・今月など）はワンタップ
- **詳細条件** を開くと、地方・都道府県・主催者・定員・参加費・開催日・並び替え
- 絞り込むと**URLが変わります**。そのURLをコピーして送れば、相手にも同じ条件で表示されます
- 検索は端末の中だけで動くので、何回操作してもGitHubには負荷がかかりません

---

# B. Discord bot を作る

## B-0. 先に全体像

やることは4つです。**それぞれ別のサイトで作業する**ので、混乱しないよう順番に進めてください。

```
① Discord Developer Portal   … botの「身分証」を作る（3つの値を控える）
② Cloudflare                 … コマンドを受け取るプログラムを置く
③ Discord Developer Portal   … 受け取り先URLを①に登録する
④ GitHub                     … スラッシュコマンドをDiscordに登録する
```

**用語の注意（ここでつまずく人が一番多いです）**

| 名前 | どこにある | 何に使う | 秘密？ |
|---|---|---|---|
| **Application ID** | General Information | ④で使う | 公開してよい |
| **Public Key** | General Information | ②で使う | 公開してよい |
| **Bot Token** | Bot タブ | ④で使う | **絶対に人に見せない** |
| Webhook URL | （`SETUP.md`で作ったもの） | 通知用。**ここでは使いません** | 見せない |

Public Key と Bot Token は**まったくの別物**です。取り違えると④で `401` エラーになります。

---

## B-1. Discordアプリを作る

1. <https://discord.com/developers/applications> を開き、Discordアカウントでログイン。
2. 右上の **New Application** をクリック。
3. 名前に `Xrossstars大会bot` などを入れ、規約にチェックして **Create**。

### 3つの値を控える

4. 左メニュー **General Information** を開きます。
   - **APPLICATION ID** の下の **Copy** → メモ帳などに貼る
   - **PUBLIC KEY** の下の **Copy** → 同じくメモ
5. 左メニュー **Bot** を開きます。
   - **Reset Token**（または **View Token**）をクリック → 確認 → 表示されたトークンを **Copy** → メモ
   - ⚠️ このトークンは**一度しか表示されません**。閉じてしまったら Reset Token で作り直せます。
   - ⚠️ SNSやスクリーンショットに絶対に写さないでください。

### botを自分のサーバーに入れる

6. 左メニュー **OAuth2** → **OAuth2 URL Generator**（または **URL Generator**）を開きます。
7. **SCOPES** で次の2つにチェック。

   - ✅ `bot`
   - ✅ `applications.commands` ← これが無いとスラッシュコマンドが出ません

8. **BOT PERMISSIONS** は何もチェックしなくて構いません
   （このbotは自分から発言せず、コマンドに応答するだけです）。
9. 一番下の **GENERATED URL** を **Copy** し、ブラウザのアドレスバーに貼って開きます。
10. 通知を受け取っているサーバーを選び、**認証** → **はい** を押します。

サーバーのメンバー一覧に、オフライン状態のbotが増えていれば成功です。
（このbotは常時接続しないので、**ずっとオフライン表示のままで正常**です。）

---

## B-2. Cloudflare に受け取り役を置く

> Cloudflare Workers の無料枠は **1日10万リクエスト**です。個人利用で使い切ることはまずありません。
> クレジットカードの登録なしで始められます。

### アカウントを作る

1. <https://dash.cloudflare.com/sign-up> でメールアドレスとパスワードを入れて登録。
2. 確認メールのリンクを開いて有効化します。
3. 「サイトを追加してください」という案内が出ますが、**追加しなくて構いません**。
   独自ドメインが無くても Workers は使えます。

### Worker を作る

4. 左メニューの **Compute** の中の **Workers & Pages**（または直接 **Workers & Pages**）を開きます。
5. **Create**（作成）→ **Workers** タブ → **Create Worker** をクリック。
6. 名前を `xrossstars-bot` などにして **Deploy**（デプロイ）。
   - この名前がURLになります: `https://xrossstars-bot.<あなたのサブドメイン>.workers.dev`
   - 初回はサブドメイン名を決める画面が出ることがあります。好きな名前で構いません。
7. デプロイ後の画面で **Edit code**（コードを編集）をクリック。

### コードを貼り付ける

8. 左側のエディタに `export default { async fetch(...) }` などのサンプルが入っています。
   **すべて選択して削除**してください（Windowsは `Ctrl+A` → `Delete`、Macは `⌘+A` → `Delete`）。
9. zipの中の **`bot/worker.bundle.js`** をテキストエディタで開き、
   **中身を全部コピー**して、空にしたエディタに貼り付けます。
   - ⚠️ `bot/worker.js` ではなく **`worker.bundle.js`** です。
     `worker.js` 単体では動きません（検索部分が入っていないため）。
10. 右上の **Deploy**（デプロイ）→ 確認が出たらもう一度 **Deploy**。

### 3つの設定値を入れる

11. 上部の **←** などでWorkerの管理画面に戻り、**Settings**（設定）タブを開きます。
12. **Variables and Secrets**（変数とシークレット / 環境変数）の欄で **Add**（追加）を押し、
    次の3つを登録します。

    | 種類 | 名前 | 値 |
    |---|---|---|
    | **Secret**（暗号化） | `DISCORD_PUBLIC_KEY` | B-1で控えた **Public Key** |
    | Text（平文でOK） | `DATA_URL` | 下の説明を参照 |
    | Text（平文でOK） | `SITE_URL` | A-1で控えたPagesのURL |

    `DATA_URL` は大会データの置き場所です。次の形になります（`<ユーザー名>` を置き換え）。

    ```
    https://raw.githubusercontent.com/<ユーザー名>/xrossstars-tonamel-watcher/main/data/known_competitions.json
    ```

    自信がなければ、GitHubで `data/known_competitions.json` を開き、**Raw** ボタンを押して
    アドレスバーのURLをコピーするのが確実です。

13. **Save**（保存）を押します。**保存後にもう一度 Deploy が必要な場合があります。**

### 生きているか確認する

14. Workerの管理画面に出ている `https://xrossstars-bot.*.workers.dev` を
    **ブラウザで開いて**みてください。

    ```
    Xrossstars 大会bot は動作しています。DiscordのInteractions Endpoint URLに
    このURLを設定してください。
    ```

    と表示されれば成功です。**このURLを控えてください。**

    - 何も出ない／エラーが出る場合 → コードの貼り付けが途中で切れていないか確認してください。

---

## B-3. Discordに受け取り先を教える

1. <https://discord.com/developers/applications> に戻り、作ったアプリを開きます。
2. 左メニュー **General Information** の下の方にある
   **INTERACTIONS ENDPOINT URL** に、B-2で控えたWorkerのURLを貼り付けます。
3. **Save Changes** をクリック。

保存を押すと、Discordがそのアドレスに**テスト用の通信を送って確かめます**。
数秒待って保存できれば、署名の検証が正しく動いているということです。

> **`Interactions endpoint URL could not be verified` と出たら**
>
> - `DISCORD_PUBLIC_KEY` に Bot Token を入れていませんか（Public Key と取り違えていないか）
> - Public Key の前後に空白や改行が入っていませんか
> - 環境変数を追加したあと **Deploy** し直しましたか
> - URLの末尾に余計な文字が付いていませんか

---

## B-4. スラッシュコマンドを登録する

コマンドの一覧（`bot/commands.json`）をDiscordに教えます。
手元にNode.jsなどを入れなくても、**GitHubの画面から実行できる**ようにしてあります。

### サーバーIDを調べる

1. Discordの **ユーザー設定** → **詳細設定** → **開発者モード** をオンにします。
2. 左のサーバーアイコンを右クリック → **サーバーIDをコピー**。

（この手順を飛ばすこともできますが、その場合コマンドが使えるようになるまで最大1時間かかります。）

### GitHubに2つのSecretを登録する

3. GitHubのリポジトリ → **Settings** → **Secrets and variables** → **Actions**。
4. **New repository secret** で次の2つを登録します。

   | Name | Secret |
   |---|---|
   | `DISCORD_APP_ID` | B-1で控えた **Application ID** |
   | `DISCORD_BOT_TOKEN` | B-1で控えた **Bot Token** |

### 実行する

5. リポジトリの **Actions** タブ → 左の **Discordのスラッシュコマンドを登録** をクリック。
6. **Run workflow** を押し、**サーバーID** の欄に手順2でコピーしたIDを貼って、
   もう一度 **Run workflow**。
7. 20秒ほどで緑のチェックになり、実行結果の画面に登録されたコマンドが表示されます。

```
## スラッシュコマンドを登録しました
- `/list` （日本語表示: /一覧）
- `/search` （日本語表示: /検索）
```

---

## B-5. 動かしてみる

Discordのチャット欄で `/` を打つと、候補に **一覧** と **検索** が出てきます。

| 打つもの | 出るもの |
|---|---|
| `/一覧` | 今後の大会が開催日順に、1ページ8件ずつ |
| `/一覧 形式:オンライン` | オンライン開催だけ |
| `/検索 キーワード:初心者` | 大会名・会場・主催者に「初心者」を含むもの |
| `/検索 都道府県:東京 無料のみ:True` | 東京都で参加費が無料のもの |
| `/検索 期間:今週末 形式:オフライン` | 今週末の現地開催 |
| `/検索 定員下限:32 参加費上限:1000` | 定員32人以上かつ1000円以下 |

- 件数が多いときは **◀ 前へ / 次へ ▶** で送れます。
- **Webで見る** を押すと、同じ条件のままWebページが開きます。
- キーワードはスペース区切りで**すべてを含むもの**を探します（`オンライン 初心者` など）。
- 都道府県は `東京` でも `東京都` でも通ります。

---

## B-6. うまくいかないとき

### `/` を打ってもコマンドが出てこない

- サーバーIDを入れずに登録した → 反映まで最大1時間かかります。サーバーIDを入れて再実行してください。
- B-1の手順7で `applications.commands` にチェックを入れ忘れた
  → もう一度URLを作り直して、botを入れ直してください。
- Discordアプリを再起動すると出ることがあります（`Ctrl+R` / `⌘+R`）。

### 「アプリケーションが応答しませんでした」と出る

Workerが動いていないか、URLの設定が間違っています。

1. Workerの `*.workers.dev` をブラウザで開いて「動作しています」が出るか確認
2. Cloudflareの Worker 画面の **Logs**（ログ）を開いた状態でコマンドを打つと、
   何が起きているか見えます
3. `DATA_URL` が正しいか（ブラウザで開いてJSONが表示されるか）を確認

### 「⚠️ うまく取得できませんでした」と返ってくる

`DATA_URL` が間違っているか、リポジトリが非公開になっています。
そのURLをブラウザで開いて、JSONがそのまま表示されるか確かめてください。

### コマンド登録が `401` / `403` / `404` で失敗する

- `401` → `DISCORD_BOT_TOKEN` が違います（Public Key を入れていませんか）
- `403` → botがそのサーバーに入っていません（B-1の手順9〜10）
- `404` → `DISCORD_APP_ID` かサーバーIDが違います

### 検索結果が0件ばかりになる

`data/known_competitions.json` に大会が入っているか確認してください。
`prefecture` や `capacity_num` が空の大会は、地域や定員での絞り込みに引っかかりません
（Tonamel側の記載が自由文で、推定できなかった場合です）。キーワード検索は効きます。

---

## B-7. あとから変えたいとき

| したいこと | やること |
|---|---|
| コマンドの説明や選択肢を変える | `bot/commands.json` を編集 → Actionsの登録ワークフローを再実行 |
| 検索の条件を変える | `bot/search.js` と `src/search.py` を**両方**直す → `python -m src.build_bot` → Cloudflareに貼り直し |
| 1ページの表示件数を変える | `bot/worker.js` の `PER_PAGE` → `python -m src.build_bot` → 貼り直し |
| botをやめる | Cloudflareの Worker を削除し、Discord Developer Portal でアプリを削除 |

`bot/worker.js` を直したときは、**必ず `python -m src.build_bot` で
`bot/worker.bundle.js` を作り直してから貼り付けてください。**
貼るのは常に `worker.bundle.js` のほうです。

> Cloudflare や Discord の画面の文言は、サービス側の更新で変わることがあります。
> ボタン名が少し違っても、やることは「コードを貼る」「環境変数を入れる」「URLを登録する」の3つです。
