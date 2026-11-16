# ふたり暮らしアプリ — 開発の引き継ぎメモ

AI エージェント（Cursor / Claude など）と人が、途中から開発を続けるためのメモです。
作業を進めたら「進み具合」のチェックを更新してください。

## これは何か

同居する二人が使う生活アプリ。家事・買い物リスト・献立・タスク・予定・在庫・生活メモを1つにまとめる。
家計簿などお金の管理は対象外（OsidOri など既存アプリに任せる）。

- 言語・フレームワーク: Python + Flask（サーバー側で HTML を描画、Jinja テンプレート）
- デプロイ: Vercel（`app.py` の `app` が入口）
- データベース: Supabase の PostgreSQL。ローカルとテストは SQLite
- ログイン: Supabase Auth（メール＋パスワード、Google）。`SUPABASE_URL` が無いときだけ開発用のローカル認証
- 端末: 二人とも iPhone。PWA としてホーム画面に追加して使う

## 決まっている方針

- 入力と編集はアプリだけで行う。Google カレンダーへは一方向に反映する（アプリ → カレンダー）
- Apple のリマインダーとは連携しない。代わりにアプリのプッシュ通知を使う
- 家事は固定担当が基本。担当外の人が完了してもよく、実際に完了した人を記録して偏りを表示する
- データは「世帯」単位。予定だけは個人のものがあり、公開範囲（非公開 / 時間だけ / 内容も）を選べる
- 世帯は最大2人。招待コードで参加する

## 構成

```
app.py                  入口（Vercel がここの app を読む）
futari/__init__.py      create_app（設定、共通のテンプレート変数）
futari/db.py            DB 接続の薄いラッパー。SQL は `?` プレースホルダで統一
futari/auth.py          Supabase Auth / ローカル認証、CSRF、login_required
futari/logic.py         日付、家事・予定が「その日に当たるか」、公開範囲の判定
futari/push.py          Web Push 送信（pywebpush）
futari/views/core.py    ログイン、世帯、ホーム、設定、通知、カレンダー配信、書き出し
futari/views/daily.py   家事、買い物、献立、レシピ
futari/views/extra.py   タスク、予定、在庫、生活メモ
futari/templates/       画面（base.html と _macros.html が共通部品）
public/                 静的ファイル（Vercel が CDN で配信）。static/app.css, static/app.js, sw.js
supabase/schema.sql     テーブル定義（Supabase の SQL Editor で実行。SQLite でも同じファイルを使う）
gas/calendar_sync.gs    Google カレンダーへ予定を書き込む GAS
tests/                  pytest
```

## 守ること

- SQL は PostgreSQL と SQLite の両方で動く書き方にする。日付は `YYYY-MM-DD` の文字列、真偽値は 0/1、ID は Python 側で作る文字列
- 更新・削除の SQL には必ず `household_id = ?` を付け、他の世帯のデータに触れないようにする
- POST のフォームには `{{ csrf() }}` を入れる（`auth.check_csrf` が全 POST を検査する）
- テーブルを増やしたら `supabase/schema.sql` に追加し、末尾の RLS 有効化にも1行足す
  （アプリはサーバーから直接 DB につなぐ。RLS は Supabase の公開 API から読めなくするための設定）
- 静的ファイルは `public/` に置く（Vercel では Flask の static フォルダ配信を使わない）
- 画面の文言は日本語。デザインは `public/static/app.css` の変数（生成りの背景、二人それぞれの色）に合わせる

## ローカルでの動かし方

```
pip install flask requests pytest
python app.py          # http://localhost:5000 （SQLite の local.db ができる）
python -m pytest -q
```

## 進み具合

- [x] DB 定義、DB ラッパー、認証、世帯の作成と招待
- [x] 画面のルート（views）一式
- [ ] テンプレート: base / login / welcome / home は作成済み。残り: chores, shopping, meals, recipes, tasks, calendar, pantry, notes, more, settings
- [ ] `public/static/app.js`（フォームの非同期送信、自動更新、通知の登録）、`public/sw.js`、`public/manifest.webmanifest`、アイコン
- [ ] `vercel.json`（毎朝の通知用 Cron）、`.env.example`、`scripts/generate_vapid.py`
- [ ] `gas/calendar_sync.gs`
- [ ] テスト（tests/test_app.py）
- [ ] README（Supabase と Vercel の設定手順）
