# ソムリエ1問一答の自動投稿 説明書

毎日 **朝7:00（問題＋カード画像）** と **夜20:50（解答）** に、
**Instagram（@Millegrains）／Facebookページ（ミルグラン）／Threads** の3か所へ自動で投稿する仕組みです。
GitHub の自動実行機能（GitHub Actions）で動くので、パソコンを閉じていても投稿されます。料金はかかりません。

> X（旧Twitter）はこの仕組みの対象外です。

---

## 1. 全体の流れ

| 時刻（日本時間） | やること |
|---|---|
| 朝 7:00 | 3か所すべてに「カード画像＋朝の本文」を投稿 |
| 夜 20:50 | 朝の投稿の下に解答を付ける（Instagram・Facebook＝コメント、Threads＝返信）<br>朝の投稿が失敗していた所だけは、カード画像付きの単独投稿にする |
| 毎月1日 9:00 | Threadsの合鍵（60日で切れる）を自動で延長 |

- 投稿するのは **日本時間の「今日」の分だけ** です。過ぎた日の分はさかのぼって投稿しません。
- 2027/09/09 の分を投稿し終えたら、あとは何もせず静かに終わります。
- GitHub の混雑で数分〜十数分遅れることがありますが、「朝の目覚まし」「夜の目覚まし」のどちらで起きたかで判断するので、朝と夜を取り違えることはありません。
- 同じ日・同じ回・同じ投稿先は、記録（`autopost/state.json`）を見て二重に投稿しません。
- 1か所が失敗しても、他の2か所はそのまま投稿します。1か所でも失敗すると、GitHubから **失敗のお知らせメール** が届きます。

### ファイルの置き場所

| ファイル | 役割 |
|---|---|
| `sommelier/source/tweets_x_full.txt` | 原稿（X用に作ったもの） |
| `sommelier/source/card_attach_guide.txt` | 日付→カード番号の対応表 |
| `sommelier/posts.json` | 原稿を日付ごとに整理した台帳（プログラムが読むのはこれ） |
| `sommelier/build_posts.py` | 原稿から台帳を作り、対応表と食い違いがないか自動チェックする |
| `autopost/post.py` | 台帳から今日の分を探して投稿する本体 |
| `autopost/state.json` | 投稿済みの記録（自動で書き込まれます。手で消さないでください） |
| `autopost/exams.json` | 資格ごとの設定（台帳の場所、画像アドレス、Instagram用の置き換え文） |
| `.github/workflows/sommelier-autopost.yml` | 朝・夜の目覚まし時計 |
| `.github/workflows/threads-token-refresh.yml` | Threadsの合鍵を毎月延長する目覚まし時計 |

### 本文の書き換え（自動）

- **Instagram**：本文のリンクは押せないので、`iOS → …` と `Android → …` の2行を
  `📲 アプリはプロフィールのリンクから（iOS／Android 無料）` の1行に置き換えます。
  → Instagramのプロフィールのリンク欄に、アプリのリンクを入れておいてください。
- **Facebookページ・Threads**：原稿のまま（リンクは押せます）。

---

## 2. 本人がやる準備（最初の1回だけ）

> Meta の画面は時期によって表記や場所が少し変わることがあります。見つからないときは、似た名前のボタンを探してください。

### ① Instagram をプロアカウントにして、Facebookページとつなぐ
1. Instagramアプリで @Millegrains を開く → 右上の **≡** → **設定とアクティビティ**
2. **アカウントの種類とツール** → **プロアカウントに切り替える** → **ビジネス** を選ぶ
3. 設定の **アカウントセンター** から、ミルグランのFacebookページ（を管理しているFacebookアカウント）とつなぐ
   - または Facebookページ側で **設定** → **リンク済みのアカウント** → **Instagram** → つなぐ

### ② Threads を開設する
1. Threadsアプリを入れて、**@Millegrains のInstagramでログイン** する
2. プロフィールを作って、Threadsを開設する

### ③ Meta for Developers でアプリ（投稿用の窓口）を作る
1. https://developers.facebook.com/ に、ミルグランのFacebookページを管理しているFacebookアカウントでログインし、開発者登録する
2. **マイアプリ** → **アプリを作成**
3. アプリ名（例：`millegrains-autopost`）を入れ、「ユースケース」で次の3つを追加する
   - **ページのすべてを管理**（Manage everything on your Page）… Facebookページへの投稿・コメント
   - **Instagramでメッセージとコンテンツを管理**（Manage messaging & content on Instagram）… Instagramへの投稿・コメント（「Facebookログイン」を使う方）
   - **Threads APIにアクセス**（Access the Threads API）
4. それぞれのユースケースの「カスタマイズ」で、次の許可を **追加** しておく

   | 投稿先 | 必要な許可 |
   |---|---|
   | Facebookページ | `pages_show_list` `pages_read_engagement` `pages_manage_posts` `pages_manage_engagement` |
   | Instagram | `instagram_basic` `instagram_content_publish` `instagram_manage_comments` `business_management` |
   | Threads | `threads_basic` `threads_content_publish` `threads_manage_replies` |

5. アプリは **開発モードのまま** で大丈夫です（自分のアカウントにだけ投稿するので、審査＝アプリレビューは基本的に不要の想定）。
   - もし途中で「アプリレビューが必要」「ビジネス認証が必要」と出て先に進めない場合は、そこで止めて相談してください。

### ④ Facebookページ用の **無期限の合鍵** を作る（Instagramにも同じ合鍵を使います）
1. https://developers.facebook.com/tools/explorer/ （グラフAPIエクスプローラ）を開く
2. 右側の **Metaアプリ** で③のアプリを選ぶ → **ユーザーまたはページ** で「ユーザートークン」
3. **許可を追加** で、上の表の Facebookページ と Instagram の許可をすべて選ぶ → **Generate Access Token** → ミルグランのページとInstagramにチェックして許可
4. 表示された合鍵の左の **ⓘ** → **アクセストークンツールで開く** → 下の **アクセストークンを延長** を押す（＝60日の合鍵になる）→ 出てきた長い合鍵をコピー
5. エクスプローラに戻り、その長い合鍵を貼り付けて、上の欄に `me/accounts` と入れて **送信**
6. 結果の中から「ミルグラン」のところを探し、
   - `access_token` … これが **Facebookページ用の無期限の合鍵**（→ `META_PAGE_ACCESS_TOKEN`）
   - `id` … これが **Facebookページの番号**（→ `FB_PAGE_ID`）
7. 念のため https://developers.facebook.com/tools/debug/accesstoken/ にその合鍵を貼って **デバッグ** → 「有効期限：なし（Never）」になっていればOK
8. エクスプローラで、合鍵を6.の無期限の合鍵に替え、上の欄に `（ページの番号）?fields=instagram_business_account` と入れて **送信**
   - `instagram_business_account` の中の `id` … これが **Instagramの番号**（→ `IG_USER_ID`）

### ⑤ Threads の合鍵と番号を作る
1. アプリの画面で **アプリの役割** → **役割** → **Threadsテスター** に @Millegrains を追加
2. Threadsアプリ（またはWeb版）で **設定** → **アカウント** → **ウェブサイトのアクセス許可** → **招待** から承認
3. アプリの画面の Threads のユースケース → **設定** の「ユーザートークン生成ツール」で @Millegrains の合鍵を発行してコピー（→ `THREADS_ACCESS_TOKEN`）
   - ここで出る合鍵は60日で切れますが、⑦の仕組みが毎月自動で延長します
4. ブラウザのアドレス欄に次を入れて開く（`合鍵` の部分を3.の合鍵に置き換え）
   `https://graph.threads.net/v1.0/me?fields=id,username&access_token=合鍵`
   - 表示された `id` が **Threadsの番号**（→ `THREADS_USER_ID`）

### ⑥ GitHubの個人用合鍵を作る（Threads合鍵の自動延長に使う）
1. GitHub 右上の自分のアイコン → **Settings** → 左下 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. 名前：`sns-cards secrets 更新用`、有効期限：できるだけ長く（期限が来たら作り直し）
3. **Repository access**：**Only select repositories** → `millegrains/sns-cards` だけ
4. **Permissions** → **Repository permissions** → **Secrets** を **Read and write** にする（他は触らなくてよい）
5. **Generate token** → 表示された合鍵をコピー（→ `GH_PAT_FOR_SECRETS`）

### ⑦ 金庫（GitHub Secrets）に登録する
`millegrains/sns-cards` の **Settings** → **Secrets and variables** → **Actions** → **Secrets** タブ → **New repository secret** で、次の6つを1つずつ登録します。

| 名前（そのまま入力） | 中身 |
|---|---|
| `META_PAGE_ACCESS_TOKEN` | ④-6 のページ用の無期限の合鍵 |
| `FB_PAGE_ID` | ④-6 のページの番号 |
| `IG_USER_ID` | ④-8 のInstagramの番号 |
| `THREADS_ACCESS_TOKEN` | ⑤-3 のThreadsの合鍵 |
| `THREADS_USER_ID` | ⑤-4 のThreadsの番号 |
| `GH_PAT_FOR_SECRETS` | ⑥ のGitHubの個人用合鍵 |

> 合鍵や番号は、絶対に保管庫のファイルやメモに書かないでください（この保管庫は公開されています）。

---

## 3. 本番前の確認（必ずこの順番で）

手動ボタンの場所：保管庫の **Actions** タブ → 左の **ソムリエ自動投稿** → 右の **Run workflow**

1. **試し（dry-run）**：`mode` を `dry-run` のまま **Run workflow**
   - 台帳が366日分そろっていて、対応表と一致しているかの自動チェックが走ります
   - 「明日の朝・夜に、何が・どこへ・どんな文で出るか」が画面（実行結果のログ）に表示されます
   - 日付欄に `2026-12-01` のように入れると、その日の分を表示します
2. **本番テスト（朝）**：`slot`＝`morning`、`mode`＝`live` で実行 → **今日の朝の分** が3か所に投稿されます
   - Instagram・Facebookページ・Threads を目で確認してください
3. **本番テスト（夜）**：`slot`＝`evening`、`mode`＝`live` で実行
   - Instagram・Facebookはコメント、Threadsは返信として、朝の投稿の下に付くことを確認してください
   - ※同じ日に自動実行の時刻が来ても、テストで投稿済みの分は二重には出ません
4. 問題なければ **自動実行を有効にする**（↓「4. 止め方・再開の仕方」）

---

## 4. 止め方・再開の仕方

自動実行は、スイッチとなる **変数 `AUTOPOST_ENABLED`** が `true` のときだけ動きます。

- **有効にする（再開する）**：**Settings** → **Secrets and variables** → **Actions** → **Variables** タブ
  → **New repository variable**（すでにあれば鉛筆マーク）→ 名前 `AUTOPOST_ENABLED`、値 `true`
- **止める**：同じ場所で値を `false` に変える（または変数を削除）
- **完全に止める**：**Actions** タブ → **ソムリエ自動投稿** → 右上の **…** → **Disable workflow**
  （再開は同じ場所の **Enable workflow**）

止めている間の日の分は、再開してもさかのぼって投稿されません（再開した日の分から投稿されます）。

---

## 5. 失敗のメールが来たとき

1. メールのリンク（または **Actions** タブの赤い✕）を開き、「本番の投稿」のログを見る
2. 日本語で理由が出ています。よくある例：

| ログの文 | 直し方 |
|---|---|
| 「Instagramの合鍵（アクセストークン）が期限切れか無効です」 | ↓「合鍵の作り直し」 |
| 「投稿の許可（権限）が足りません」 | 2-③の許可を追加し、合鍵を作り直す |
| 「金庫に次の値が登録されていません」 | 2-⑦の登録漏れ |
| 「カード画像を取りに来られませんでした」 | 画像が保管庫の `main` にあるか確認 |
| 「投稿回数の制限に引っかかりました」 | 時間をおいて手動で再実行 |

3. 直したら、手動ボタンで **同じ回を `live` で実行** すると、**失敗した所だけ** 投稿されます（成功した所は記録済みなのでスキップ）。
   - ただし投稿されるのは「今日」の分だけです。日付が変わってしまった分はさかのぼれません。

### 合鍵の作り直し
- **Facebookページ・Instagram**：2-④をもう一度やり、金庫の `META_PAGE_ACCESS_TOKEN` を新しい合鍵で **Update** する
  （Facebookのパスワードを変えたり、アプリの許可を外したりすると、無期限の合鍵も無効になります）
- **Threadsの合鍵を作り直す**：2-⑤-3 をもう一度やり、金庫の `THREADS_ACCESS_TOKEN` を Update する
  （「Threads合鍵の自動延長」が失敗したまま60日たつと、こうなります）
- **GitHubの個人用合鍵**：期限が来たら2-⑥で作り直し、金庫の `GH_PAT_FOR_SECRETS` を Update する

---

## 6. 原稿を直したいとき

1. `sommelier/source/tweets_x_full.txt`（必要なら `card_attach_guide.txt` も）を新しいものに差し替える
2. パソコンで保管庫のフォルダを開き、次を実行（Pythonが必要です）
   ```
   python sommelier/build_posts.py
   ```
   「✅ チェック合格」と出たら、`sommelier/posts.json` ごと保管庫に上げる（コミット＆プッシュ）
3. Actions の手動ボタンで dry-run を実行して、表示を確認する

---

## 7. 知っておくとよいこと

- **Metaの窓口の版（API バージョン）**：古い版は2年ほどで使えなくなります。初期値は `v26.0` です。
  もし「バージョンが古い」という失敗が出たら、**Variables** に `META_GRAPH_VERSION`（値の例：`v27.0`）を追加すれば、プログラムを直さずに切り替えられます。
- GitHub は、保管庫に60日間まったく変更がないと自動実行を止めることがありますが、この仕組みは毎日投稿記録を書き込むので、その心配はありません。
- 自動実行はふだん数分程度、混雑時は十数分ほど遅れることがあります。

---

## 8. 他の資格（宅建・管業・マン管・賃管）を足すとき

同じ仕組みで流せるように作ってあります。

1. その資格の台帳（例：`takken/posts.json`、形式は `sommelier/posts.json` と同じ）を作る
2. `autopost/exams.json` に資格を1つ追加する（台帳の場所・画像アドレス・Instagram用の置き換え文・投稿先）
3. `.github/workflows/sommelier-autopost.yml` を複製して名前を変え、`--exam takken` にする
   （投稿するアカウントが違う場合は、金庫の名前も資格ごとに分けて、そのワークフローで読み替える）
