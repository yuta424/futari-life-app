"""ローカル認証 + SQLite で、主な流れをひととおり確認する。"""
import json
import re
from datetime import timedelta

import pytest

from futari import create_app, logic, push


@pytest.fixture()
def app(tmp_path):
    return create_app(
        {
            "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
            "TESTING": True,
            "SUPABASE_URL": "",
            "VAPID_PUBLIC_KEY": "pub",
            "VAPID_PRIVATE_KEY": "priv",
            "CRON_SECRET": "cron-secret",
        }
    )


class User:
    """1人分のブラウザ。CSRF トークンを自動で付けて POST する。"""

    def __init__(self, app, email):
        self.c = app.test_client()
        self.email = email
        self.post("/login", mode="signup", email=email, password="password1")

    def token(self):
        html = self.c.get("/login", follow_redirects=True).get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, url, _follow=True, **data):
        data["_csrf"] = self.token()
        return self.c.post(url, data=data, follow_redirects=_follow)

    def get(self, url):
        r = self.c.get(url, follow_redirects=True)
        return r.get_data(as_text=True)


def find_id(html, pattern):
    return re.search(pattern, html).group(1)


@pytest.fixture()
def pair(app):
    """同じ世帯の二人（ゆうた・ゆみ）。"""
    a = User(app, "a@example.com")
    a.post("/welcome", display_name="ゆうた", color="sora", action="create", household_name="テスト家")
    code = find_id(a.get("/settings"), r'class="code">([A-Z0-9]{8})<')
    b = User(app, "b@example.com")
    r = b.post("/welcome", display_name="ゆみ", color="momo", action="join", invite_code=code)
    assert "ゆみさんの今日" in r.get_data(as_text=True)
    return a, b


def test_login_required_and_wrong_password(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    User(app, "x@example.com")
    other = app.test_client()
    html = other.get("/login").get_data(as_text=True)
    tok = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    r = other.post("/login", data={"_csrf": tok, "email": "x@example.com", "password": "wrong-pass"})
    assert "メールアドレスかパスワードが違います" in r.get_data(as_text=True)


def test_post_without_csrf_is_rejected(pair):
    a, _ = pair
    r = a.c.post("/shopping/add", data={"name": "牛乳"})
    assert r.status_code == 400
    assert "牛乳" not in a.get("/shopping")


def test_household_is_limited_to_two(app, pair):
    a, _ = pair
    c = User(app, "c@example.com")
    # 2人そろうと招待コードは設定画面に出ないので、DB から直接読む
    with app.app_context():
        from futari.db import get_db

        code = get_db().one("select invite_code from households")["invite_code"]
    r = c.post("/welcome", display_name="だれか", color="fuji", action="join", invite_code=code)
    assert "すでに二人が参加しています" in r.get_data(as_text=True)


def test_chore_done_by_partner_is_recorded(pair):
    a, b = pair
    a.post("/chores/add", name="お風呂掃除", freq_type="daily")
    html = a.get("/chores")
    assert "お風呂掃除" in html and "毎日" in html
    chore_id = find_id(html, r"/chores/([0-9a-f]{32})/toggle")
    b.post(f"/chores/{chore_id}/toggle")
    html = a.get("/")
    assert "が完了" in html and "ゆみ" in html
    # もう一度押すと取り消せる
    b.post(f"/chores/{chore_id}/toggle")
    assert "が完了" not in a.get("/")


def test_weekly_chore_only_on_selected_days(pair):
    a, _ = pair
    today = logic.today()
    other_day = (today.weekday() + 3) % 7
    a.post("/chores/add", name="今日の曜日の家事", freq_type="weekly", weekdays=str(today.weekday()))
    a.post("/chores/add", name="別の曜日の家事", freq_type="weekly", weekdays=str(other_day))
    home = a.get("/")
    assert "今日の曜日の家事" in home
    assert "別の曜日の家事" not in home
    r = a.post("/chores/add", name="曜日なし", freq_type="weekly")
    assert "曜日を1つ以上選んでください" in r.get_data(as_text=True)


def test_shopping_shared_and_no_duplicates(pair):
    a, b = pair
    a.post("/shopping/add", name="牛乳", qty="2本")
    html = b.get("/shopping")
    assert "牛乳" in html and "卵・乳製品" in html and "残り1件" in html
    r = b.post("/shopping/add", name="牛乳")
    assert "すでにリストにあります" in r.get_data(as_text=True)
    item_id = find_id(html, r"/shopping/([0-9a-f]{32})/toggle")
    b.post(f"/shopping/{item_id}/toggle")
    assert "買うものはありません" in a.get("/shopping")
    a.post("/shopping/clear-done")
    assert "牛乳" not in a.get("/shopping").replace("牛乳パック", "")


def test_meal_ingredients_go_to_shopping(pair):
    a, b = pair
    a.post("/recipes/save", name="肉じゃが", ingredients="じゃがいも 3個\n玉ねぎ 1個\n牛肉 200g")
    day = logic.today().isoformat()
    a.post("/meals/set", day=day, slot="dinner", title="肉じゃが")
    html = b.get("/meals")
    assert "肉じゃが" in html
    meal_id = find_id(html, r"/meals/([0-9a-f]{32})/to-shopping")
    r = b.post(f"/meals/{meal_id}/to-shopping")
    assert "3件、買い物リストに追加しました" in r.get_data(as_text=True)
    shop = a.get("/shopping")
    assert "じゃがいも" in shop and "3個" in shop and "牛肉" in shop
    # 2回目は重複させない
    r = b.post(f"/meals/{meal_id}/to-shopping")
    assert "すべてリストに入っています" in r.get_data(as_text=True)
    assert "肉じゃが" in a.get("/")
    # 空にすると未定に戻る
    a.post("/meals/set", day=day, slot="dinner", title="")
    assert "肉じゃが" not in a.get("/")


def test_task_assign_notifies_partner(pair, monkeypatch):
    a, b = pair
    sent = []
    monkeypatch.setattr(push, "_send", lambda sub, payload: sent.append(payload) or "ok")
    b.c.post(
        "/push/subscribe",
        json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "s"}},
        headers={"X-CSRF-Token": b.token()},
    )
    b_id = find_id(a.get("/tasks"), r'<option value="([0-9a-f]{32})"\s*>ゆみ')
    due = (logic.today() + timedelta(days=1)).isoformat()
    a.post("/tasks/add", title="火災保険の更新", assignee_id=b_id, due_date=due)
    assert sent and "火災保険の更新" in sent[0]["body"]
    assert "期限が近いタスク" in b.get("/") and "火災保険の更新" in b.get("/")
    task_id = find_id(b.get("/tasks"), r"/tasks/([0-9a-f]{32})/toggle")
    b.post(f"/tasks/{task_id}/toggle")
    assert "最近終わったもの" in a.get("/tasks")


def test_event_visibility_between_partners(pair):
    a, b = pair
    day = logic.today().isoformat()
    a.post("/calendar/save", title="二人で外食", day=day, scope="shared", start_time="19:00")
    a.post("/calendar/save", title="サプライズ準備", day=day, scope="mine", visibility="private")
    a.post("/calendar/save", title="歯医者", day=day, scope="mine", visibility="busy", start_time="10:00")
    a.post("/calendar/save", title="飲み会", day=day, scope="mine", visibility="full")
    mine = a.get(f"/calendar?day={day}")
    for title in ("二人で外食", "サプライズ準備", "歯医者", "飲み会"):
        assert title in mine
    theirs = b.get(f"/calendar?day={day}")
    assert "二人で外食" in theirs and "飲み会" in theirs
    assert "サプライズ準備" not in theirs
    assert "歯医者" not in theirs and "予定あり" in theirs
    # 相手の予定は編集・削除できない
    with_ids = re.findall(r"/calendar/([0-9a-f]{32})/delete", mine)
    for event_id in with_ids:
        b.post(f"/calendar/{event_id}/delete")
    after = a.get(f"/calendar?day={day}")
    assert "サプライズ準備" in after and "歯医者" in after and "飲み会" in after
    assert "二人で外食" not in after  # 二人の予定はどちらも消せる
    # 配信（iCal / JSON）と書き出しでも、相手の非公開予定は出ない
    b_feed = find_id(b.get("/settings"), r'value="http://localhost(/cal/[^"]+\.ics)"')
    ics = b.get(b_feed)
    assert "BEGIN:VCALENDAR" in ics and "サプライズ準備" not in ics and "歯医者" not in ics
    assert "ゆうた: 予定あり" in ics and "ゆうた: 飲み会" in ics
    feed_json = json.loads(b.get(b_feed.replace(".ics", ".json")))
    titles = {e["title"] for e in feed_json["events"]}
    assert "ゆうた: 予定あり" in titles and not any("サプライズ" in t for t in titles)
    exported = b.get("/settings/export.json")
    assert "サプライズ準備" not in exported and "歯医者" not in exported


def test_garbage_day_shows_on_home(pair):
    a, b = pair
    today = logic.today()
    a.post("/calendar/save", kind="garbage", title="燃えるゴミ", day=today.isoformat(), weekdays=str(today.weekday()))
    a.post(
        "/calendar/save",
        kind="garbage",
        title="資源ゴミ",
        day=today.isoformat(),
        weekdays=str((today.weekday() + 1) % 7),
    )
    home = b.get("/")
    assert "今日は燃えるゴミの日" in home and "明日は資源ゴミ" in home


def test_pantry_expiry_and_rebuy(pair):
    a, b = pair
    soon = (logic.today() + timedelta(days=1)).isoformat()
    a.post("/pantry/add", name="豚こま肉", qty="2枚", expires_on=soon)
    assert "早めに使いたい食材" in b.get("/") and "豚こま肉" in b.get("/")
    item_id = find_id(b.get("/pantry"), r"/pantry/([0-9a-f]{32})/used")
    b.post(f"/pantry/{item_id}/used", rebuy="1")
    assert "豚こま肉" not in a.get("/pantry")
    assert "豚こま肉" in a.get("/shopping")


def test_notes_and_export(pair):
    a, b = pair
    a.post("/notes/save", title="洗濯機の保証", category="appliance", body="型番 ABC-123\n2031年まで")
    html = b.get("/notes")
    assert "洗濯機の保証" in html and "家電・保証" in html
    data = json.loads(b.get("/settings/export.json"))
    assert data["notes"][0]["title"] == "洗濯機の保証"
    assert {m["display_name"] for m in data["members"]} == {"ゆうた", "ゆみ"}


def test_other_household_cannot_see_or_change(app, pair):
    a, _ = pair
    a.post("/shopping/add", name="ひみつの品")
    a.post("/notes/save", title="ひみつメモ", category="other", body="x")
    item_id = find_id(a.get("/shopping"), r"/shopping/([0-9a-f]{32})/toggle")
    z = User(app, "z@example.com")
    z.post("/welcome", display_name="よそ", color="fuji", action="create", household_name="よその家")
    assert "ひみつの品" not in z.get("/shopping")
    assert "ひみつメモ" not in z.get("/notes")
    assert "ひみつ" not in z.get("/settings/export.json")
    z.post(f"/shopping/{item_id}/delete")
    z.post(f"/shopping/{item_id}/toggle")
    assert "残り1件" in a.get("/shopping")


def test_morning_cron_sends_summary(app, pair, monkeypatch):
    a, b = pair
    sent = []
    monkeypatch.setattr(push, "_send", lambda sub, payload: sent.append(payload) or "ok")
    b.c.post(
        "/push/subscribe",
        json={"endpoint": "https://push.example/b", "keys": {"p256dh": "k", "auth": "s"}},
        headers={"X-CSRF-Token": b.token()},
    )
    a.post("/chores/add", name="洗濯", freq_type="daily")
    c = app.test_client()
    assert c.get("/cron/daily").status_code == 404
    assert c.get("/cron/daily", headers={"Authorization": "Bearer wrong"}).status_code == 404
    r = c.get("/cron/daily", headers={"Authorization": "Bearer cron-secret"})
    assert r.get_json() == {"ok": True, "users": 1, "sent": 1}
    assert "洗濯" in sent[0]["body"]


def test_expired_push_subscription_is_removed(app, pair, monkeypatch):
    a, _ = pair
    monkeypatch.setattr(push, "_send", lambda sub, payload: "gone")
    a.c.post(
        "/push/subscribe",
        json={"endpoint": "https://push.example/a", "keys": {"p256dh": "k", "auth": "s"}},
        headers={"X-CSRF-Token": a.token()},
    )
    r = a.c.post("/push/test", headers={"X-CSRF-Token": a.token()})
    assert r.get_json()["sent"] == 0
    with app.app_context():
        from futari.db import get_db

        assert get_db().one("select count(*) as n from push_subscriptions")["n"] == 0


def test_all_pages_render(pair):
    a, _ = pair
    for url in ("/", "/chores", "/shopping", "/meals", "/recipes", "/tasks", "/calendar", "/pantry", "/notes", "/more", "/settings"):
        r = a.c.get(url)
        assert r.status_code == 200, url
    assert a.c.get("/sw.js").status_code == 200
    assert a.c.get("/manifest.webmanifest").status_code == 200
    assert a.c.get("/static/app.css").status_code == 200
    assert a.c.get("/nope").status_code == 404
    assert a.c.get("/cal/wrong-token.ics").status_code == 404


def test_logic_helpers():
    from datetime import date

    chore = dict(start_date="2026-11-16", freq_type="interval", interval_days=3, weekdays="")
    assert logic.chore_due_on(chore, date(2026, 11, 16))
    assert not logic.chore_due_on(chore, date(2026, 11, 17))
    assert logic.chore_due_on(chore, date(2026, 11, 19))
    assert not logic.chore_due_on(chore, date(2026, 11, 13))
    ann = dict(day="2024-03-05", repeat_type="yearly", weekdays="")
    assert logic.event_occurs_on(ann, date(2027, 3, 5)) and not logic.event_occurs_on(ann, date(2027, 3, 6))
    monthly = dict(day="2026-01-31", repeat_type="monthly", weekdays="")
    assert logic.event_occurs_on(monthly, date(2026, 3, 31)) and not logic.event_occurs_on(monthly, date(2026, 2, 28))
    assert logic.guess_category("牛乳") == "dairy" and logic.guess_category("謎の品") == "other"
