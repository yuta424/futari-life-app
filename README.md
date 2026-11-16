# ふたり暮らし

同居する二人のための生活アプリです。家事・買い物リスト・献立・タスク・予定・冷蔵庫の在庫・生活メモを1か所にまとめます。
Python（Flask）で作られていて、Vercel と Supabase で動きます。

## できること

| 画面 | 内容 |
| --- | --- |
| ホーム | 今日の家事・献立・ゴミの日・予定・期限の近いタスク・早めに使いたい食材 |
| 家事 | くり返しの家事（毎日／曜日／何日ごと）、担当、完了チェック、この30日の分担の割合 |
| 買い物 | 二人で同じリストを編集（約12秒ごとに自動更新）、売り場別の表示、よく買う物の候補 |
| 献立 | 週ごとの朝・昼・夜、レシピ帳、材料を買い物リストへ追加 |
| タスク | 一度きりのやること。相手を担当にすると通知が届く |
| 予定 | 二人の予定と個人の予定。個人の予定は「見せない／時間だけ／内容も」を選べる。ゴミの日、記念日 |
| 在庫 | 食材と期限。期限が近いとホームと朝の通知でお知らせ |
| 生活メモ | 家電の保証、契約、住まいの情報 |
| 設定 | 通知、招待コード、Google カレンダーへの反映、データの書き出し |

お金の管理（家計簿・精算）は入っていません。

## 公開までの手順

### 1. Supabase を準備する

1. [Supabase](https://supabase.com) でプロジェクトを作る（リージョンは Tokyo）。
2. **SQL Editor** を開き、`supabase/schema.sql` の中身をすべて貼り付けて実行する。
3. **Authentication → Sign In / Providers → Email** で「Confirm email」をオフにする。
   オンのままでも使えますが、登録のたびに確認メールのリンクを開く必要があります。
4. **Connect** ボタンから **Transaction pooler** の接続文字列（ポート 6543）を控える。これが `DATABASE_URL` です。
5. **Project Settings → API** で Project URL（`SUPABASE_URL`）と anon（publishable）キー（`SUPABASE_ANON_KEY`）を控える。

### 2. Vercel に公開する

1. [Vercel](https://vercel.com) で「Add New → Project」から、この GitHub リポジトリを取り込む。設定は変えなくて大丈夫です。
2. **Settings → Environment Variables** に `.env.example` の項目を登録する。
   - `SECRET_KEY` と `CRON_SECRET`: `python -c "import secrets; print(secrets.token_hex(32))"` をそれぞれ実行した値
   - `VAPID_PUBLIC_KEY` と `VAPID_PRIVATE_KEY`: `python scripts/generate_vapid.py` の出力（`pip install cryptography` が必要）
3. もう一度デプロイする（環境変数は次のデプロイから有効になります）。

### 3. ログインの戻り先を登録する

Supabase の **Authentication → URL Configuration** で次を設定します。

- Site URL: `https://あなたのアプリ.vercel.app`
- Redirect URLs: `https://あなたのアプリ.vercel.app/auth/callback`

### 4. Google ログインを有効にする（使う場合）

1. [Google Cloud Console](https://console.cloud.google.com) で OAuth クライアント ID（ウェブアプリケーション）を作る。
   承認済みのリダイレクト URI には、Supabase の **Authentication → Sign In / Providers → Google** に表示される Callback URL を入れる。
2. 同じ画面に、作ったクライアント ID とシークレットを入力して有効にする。

メールとパスワードだけで使う場合、この手順は不要です。

### 5. 二人で使い始める

1. 一人目がアカウントを作り、「新しく世帯を作る」を選ぶ。
2. 設定画面に出る8文字の招待コードを相手に伝える。
3. 二人目がアカウントを作り、招待コードを入力して参加する。
4. iPhone では Safari でアプリを開き、共有メニューから「ホーム画面に追加」する。
   ホーム画面のアイコンから開いて、設定 →「この端末で通知を受け取る」を押すと通知が届くようになります。

## Google カレンダーに予定を表示する

アプリで登録した予定を、Google カレンダーへ一方向に反映できます。予定の追加や変更はアプリで行います。

- **手軽な方法**: 設定画面のカレンダー用 URL を、Google カレンダーの「他のカレンダー ＋ → URL で追加」に貼り付ける。
  反映は Google 側の都合で数時間遅れることがあります。
- **すぐ反映したい場合**: `gas/calendar_sync.gs` を Google Apps Script に貼り付けて、15分おきに実行する。手順はファイルの先頭に書いてあります。

カレンダー用 URL は人ごとに違います。相手の個人予定は、アプリで見えている範囲（非公開は出ない、「時間だけ」は「予定あり」）で反映されます。

## 手元で動かす

```
pip install flask requests pytest
python app.py            # http://localhost:5000
python -m pytest -q
```

環境変数なしで起動すると、SQLite（`local.db`）と開発用のローカル認証で動きます。

## 確認できていること・できていないこと

自動テスト（`tests/`）と、スマホ幅のブラウザでの画面確認は SQLite とローカル認証で行いました。
次の部分は実際のサービスにつないでの確認がまだなので、公開後に一度試してください。

- Supabase の PostgreSQL への接続（`psycopg2`）と、Supabase Auth でのログイン（メール／Google）
- 実機でのプッシュ通知（`pywebpush`）と、毎朝7時ごろの Vercel Cron からの通知
- `gas/calendar_sync.gs` の実行

圏外のときは、直前に開いた画面を表示できます（チェックなどの操作は電波が戻ってから）。

## 開発を続ける人へ

構成・決まっている方針・進み具合は [AGENTS.md](AGENTS.md) にまとめています。
