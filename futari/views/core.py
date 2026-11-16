"""ログイン・世帯・ホーム・設定・通知・カレンダー配信・書き出し。"""
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from .. import auth, logic, push
from ..db import get_db, new_id, now_iso
from . import back, bp, hh, text

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "public")
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_MEMBERS = 2


# ---------- PWA のファイル（Vercel では public/ から CDN 配信される） ----------


@bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(PUBLIC_DIR, "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(PUBLIC_DIR, "manifest.webmanifest", mimetype="application/manifest+json")


# ---------- ログイン ----------


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.home"))
    mode = request.values.get("mode", "login")
    if request.method == "POST":
        email = text("email").lower()
        password = request.form.get("password") or ""
        try:
            if not email or "@" not in email:
                raise auth.AuthError("メールアドレスを入力してください。")
            if mode == "signup":
                user = auth.sign_up(email, password)
                if user is None:
                    flash("確認メールを送りました。メール内のリンクを開いてから、ここでログインしてください。", "info")
                    return redirect(url_for("main.login"))
            else:
                user = auth.sign_in(email, password)
            auth.start_session(user)
            return redirect(url_for("main.home"))
        except auth.AuthError as e:
            flash(str(e), "error")
    return render_template("login.html", mode=mode, email=request.form.get("email", ""))


@bp.route("/auth/google")
def auth_google():
    if not auth.supabase_enabled():
        abort(404)
    return redirect(auth.google_authorize_url(url_for("main.auth_callback", _external=True)))


@bp.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        flash("Googleログインを完了できませんでした。もう一度お試しください。", "error")
        return redirect(url_for("main.login"))
    try:
        user = auth.google_finish(code)
    except auth.AuthError as e:
        flash(str(e), "error")
        return redirect(url_for("main.login"))
    auth.start_session(user)
    return redirect(url_for("main.home"))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---------- はじめての設定（名前と世帯） ----------


def _new_invite_code(db):
    while True:
        code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
        if not db.one("select id from households where invite_code = ?", [code]):
            return code


@bp.route("/welcome", methods=["GET", "POST"])
def welcome():
    if g.user is None:
        return redirect(url_for("main.login"))
    if g.user["household_id"] and g.user["display_name"]:
        return redirect(url_for("main.home"))
    db = get_db()
    if request.method == "POST":
        name = text("display_name", 20)
        color = request.form.get("color") if request.form.get("color") in logic.COLORS else "anzu"
        action = request.form.get("action")
        error = None
        household_id = g.user["household_id"]
        if not name:
            error = "呼び名を入力してください。"
        elif not household_id and action == "join":
            code = text("invite_code", 12).upper().replace(" ", "").replace("-", "")
            target = db.one("select * from households where invite_code = ?", [code])
            if not target:
                error = "招待コードが見つかりません。相手の設定画面に表示されているコードを確認してください。"
            else:
                count = db.one("select count(*) as n from users where household_id = ?", [target["id"]])["n"]
                if count >= MAX_MEMBERS:
                    error = "この世帯にはすでに二人が参加しています。"
                else:
                    household_id = target["id"]
        elif not household_id:
            household_id = db.insert(
                "households",
                name=text("household_name", 30) or "わが家",
                invite_code=_new_invite_code(db),
                created_at=now_iso(),
            )
        if error:
            flash(error, "error")
        else:
            db.run(
                "update users set display_name = ?, color = ?, household_id = ? where id = ?",
                [name, color, household_id, g.user["id"]],
            )
            return redirect(url_for("main.home"))
    return render_template("welcome.html")


# ---------- ホーム ----------


def _chores_for(db, household_id, day):
    chores = db.all("select * from chores where household_id = ? and active = 1 order by created_at", [household_id])
    logs = {
        r["chore_id"]: r
        for r in db.all(
            "select * from chore_logs where household_id = ? and due_date = ?", [household_id, day.isoformat()]
        )
    }
    out = []
    for c in chores:
        if logic.chore_due_on(c, day):
            c["log"] = logs.get(c["id"])
            c["freq_label"] = logic.chore_freq_label(c)
            out.append(c)
    return out


def day_overview(db, user, day):
    """その日の「やること・食べるもの・予定」をまとめる（ホームと朝の通知で使う）。"""
    household_id = user["household_id"]
    names = {
        m["id"]: m["display_name"]
        for m in db.all("select id, display_name from users where household_id = ?", [household_id])
    }
    chores = _chores_for(db, household_id, day)
    chores.sort(key=lambda c: (c["log"] is not None, c["assignee_id"] not in (user["id"], None)))
    events = db.all("select * from events where household_id = ?", [household_id])
    todays = logic.events_on(events, day, user["id"], names)
    tomorrow = logic.events_on(events, day + timedelta(days=1), user["id"], names)
    meals = {
        m["slot"]: m
        for m in db.all("select * from meals where household_id = ? and day = ?", [household_id, day.isoformat()])
    }
    soon = (day + timedelta(days=3)).isoformat()
    tasks = db.all(
        "select * from tasks where household_id = ? and done = 0 and due_date is not null and due_date <= ?"
        " order by due_date limit 6",
        [household_id, soon],
    )
    pantry = db.all(
        "select * from pantry_items where household_id = ? and expires_on is not null and expires_on <= ?"
        " order by expires_on limit 6",
        [household_id, soon],
    )
    shopping_left = db.one(
        "select count(*) as n from shopping_items where household_id = ? and done = 0", [household_id]
    )["n"]
    return dict(
        chores=chores,
        garbage_today=[e for e in todays if e["kind"] == "garbage"],
        garbage_tomorrow=[e for e in tomorrow if e["kind"] == "garbage"],
        events=[e for e in todays if e["kind"] != "garbage"],
        events_tomorrow=[e for e in tomorrow if e["kind"] != "garbage"],
        meals=meals,
        tasks=tasks,
        pantry=pantry,
        shopping_left=shopping_left,
    )


@bp.route("/")
@auth.login_required
def home():
    day = logic.today()
    data = day_overview(get_db(), g.user, day)
    return render_template("home.html", day=day, slots=logic.MEAL_SLOTS, **data)


@bp.route("/more")
@auth.login_required
def more():
    return render_template("more.html")


# ---------- 設定 ----------


@bp.route("/settings")
@auth.login_required
def settings():
    db = get_db()
    household = db.one("select * from households where id = ?", [hh()])
    feed_url = url_for("main.calendar_feed", token=g.user["ical_token"], _external=True)
    return render_template(
        "settings.html",
        household=household,
        feed_url=feed_url,
        push_ready=push.push_enabled(),
        can_invite=len(g.members) < MAX_MEMBERS,
    )


@bp.route("/settings/profile", methods=["POST"])
@auth.login_required
def settings_profile():
    name = text("display_name", 20)
    color = request.form.get("color")
    if not name or color not in logic.COLORS:
        flash("呼び名を入力してください。", "error")
    else:
        get_db().run("update users set display_name = ?, color = ? where id = ?", [name, color, g.user["id"]])
        flash("プロフィールを保存しました。", "ok")
    return back("main.settings")


@bp.route("/settings/household", methods=["POST"])
@auth.login_required
def settings_household():
    name = text("name", 30)
    if name:
        get_db().run("update households set name = ? where id = ?", [name, hh()])
        flash("世帯の名前を保存しました。", "ok")
    return back("main.settings")


@bp.route("/settings/feed-reset", methods=["POST"])
@auth.login_required
def settings_feed_reset():
    get_db().run("update users set ical_token = ? where id = ?", [secrets.token_urlsafe(24), g.user["id"]])
    flash("カレンダー用URLを作り直しました。古いURLは使えなくなります。", "ok")
    return back("main.settings")


EXPORT_TABLES = [
    "chores",
    "chore_logs",
    "shopping_items",
    "recipes",
    "meals",
    "tasks",
    "pantry_items",
    "events",
    "notes",
]


@bp.route("/settings/export.json")
@auth.login_required
def settings_export():
    db = get_db()
    data = {
        "exported_at": now_iso(),
        "household": db.one("select id, name, created_at from households where id = ?", [hh()]),
        "members": [{"id": m["id"], "display_name": m["display_name"]} for m in g.members],
    }
    for table in EXPORT_TABLES:
        rows = db.all(f"select * from {table} where household_id = ?", [hh()])
        if table == "events":
            # 相手の個人予定は、アプリ上で見えている範囲だけを書き出す
            rows = [v for v in (logic.visible_event(r, g.user["id"], g.names) for r in rows) if v]
            for r in rows:
                for k in ("mine", "shared", "owner_name", "masked"):
                    r.pop(k, None)
        data[table] = rows
    body = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"futari-{logic.today().isoformat()}.json"
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- プッシュ通知 ----------


@bp.route("/push/subscribe", methods=["POST"])
@auth.login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys") or {}
    endpoint = data.get("endpoint") or ""
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        abort(400, description="通知の登録情報が正しくありません。")
    db = get_db()
    db.run("delete from push_subscriptions where endpoint = ?", [endpoint])
    db.insert(
        "push_subscriptions",
        user_id=g.user["id"],
        endpoint=endpoint[:1000],
        p256dh=keys["p256dh"][:300],
        auth=keys["auth"][:300],
        created_at=now_iso(),
    )
    return jsonify(ok=True)


@bp.route("/push/unsubscribe", methods=["POST"])
@auth.login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    get_db().run(
        "delete from push_subscriptions where endpoint = ? and user_id = ?", [data.get("endpoint") or "", g.user["id"]]
    )
    return jsonify(ok=True)


@bp.route("/push/test", methods=["POST"])
@auth.login_required
def push_test():
    sent = push.notify([g.user["id"]], "通知のテスト", "この端末で通知を受け取れます。", url_for("main.home"))
    return jsonify(ok=True, sent=sent)


def morning_message(overview, user):
    """朝の通知の本文。伝えることがなければ None。"""
    lines = []
    if overview["garbage_today"]:
        lines.append("ゴミの日: " + "、".join(e["title"] for e in overview["garbage_today"]))
    mine = [c for c in overview["chores"] if c["log"] is None and c["assignee_id"] in (user["id"], None)]
    if mine:
        lines.append("家事: " + "、".join(c["name"] for c in mine[:5]))
    if overview["events"]:
        lines.append(
            "予定: " + "、".join((e["start_time"] + " " if e["start_time"] else "") + e["title"] for e in overview["events"][:4])
        )
    due = [t for t in overview["tasks"] if t["assignee_id"] in (user["id"], None)]
    if due:
        lines.append("期限が近い: " + "、".join(t["title"] for t in due[:3]))
    if overview["pantry"]:
        lines.append("早めに使う: " + "、".join(p["name"] for p in overview["pantry"][:4]))
    if overview["events_tomorrow"]:
        ann = [e for e in overview["events_tomorrow"] if e["kind"] == "anniversary"]
        if ann:
            lines.append("明日は " + "、".join(e["title"] for e in ann))
    return "\n".join(lines) or None


@bp.route("/cron/daily")
def cron_daily():
    """毎朝 Vercel Cron から呼ばれ、今日のやることを通知する。"""
    secret = current_app.config.get("CRON_SECRET")
    sent_header = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(sent_header, f"Bearer {secret}"):
        abort(404)
    db = get_db()
    day = logic.today()
    users = db.all(
        "select * from users where household_id is not null"
        " and id in (select user_id from push_subscriptions)"
    )
    sent = 0
    for user in users:
        body = morning_message(day_overview(db, user, day), user)
        if body:
            sent += push.notify([user["id"]], f"{day.month}月{day.day}日のやること", body, "/")
    return jsonify(ok=True, users=len(users), sent=sent)


# ---------- カレンダー配信（Google カレンダーなどに一方向で反映） ----------


def _feed_user(token):
    user = get_db().one("select * from users where ical_token = ?", [token])
    if not user or not user["household_id"]:
        abort(404)
    return user


def _feed_events(user):
    db = get_db()
    names = {
        m["id"]: m["display_name"]
        for m in db.all("select id, display_name from users where household_id = ?", [user["household_id"]])
    }
    rows = db.all("select * from events where household_id = ? order by day", [user["household_id"]])
    return [v for v in (logic.visible_event(r, user["id"], names) for r in rows) if v]


def _feed_title(ev):
    if ev["shared"] or ev["mine"]:
        return ev["title"]
    return f"{ev['owner_name']}: {ev['title']}"


def _ical_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _utc_stamp(day, hhmm):
    local = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=logic.JST)
    return local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@bp.route("/cal/<token>.ics")
def calendar_feed(token):
    user = _feed_user(token)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//futari-life-app//JA",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:ふたり暮らし",
        "X-WR-TIMEZONE:Asia/Tokyo",
    ]
    for ev in _feed_events(user):
        day = logic.parse_date(ev["day"])
        if day is None:
            continue
        lines += ["BEGIN:VEVENT", f"UID:{ev['id']}@futari-life-app", f"DTSTAMP:{stamp}"]
        try:
            if not ev["start_time"]:
                raise ValueError
            start = _utc_stamp(day, ev["start_time"])
            end = _utc_stamp(day, ev["end_time"]) if ev["end_time"] > ev["start_time"] else None
            lines.append(f"DTSTART:{start}")
            if end:
                lines.append(f"DTEND:{end}")
        except ValueError:
            lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}")
        rt = ev["repeat_type"]
        if rt == "weekly":
            days = logic.parse_weekdays(ev["weekdays"]) or [day.weekday()]
            lines.append("RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(BYDAY[i] for i in days))
        elif rt == "monthly":
            lines.append("RRULE:FREQ=MONTHLY")
        elif rt == "yearly":
            lines.append("RRULE:FREQ=YEARLY")
        lines.append("SUMMARY:" + _ical_escape(_feed_title(ev)))
        if ev["memo"]:
            lines.append("DESCRIPTION:" + _ical_escape(ev["memo"]))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", mimetype="text/calendar; charset=utf-8")


@bp.route("/cal/<token>.json")
def calendar_feed_json(token):
    """GAS 用: 今日から60日分の予定を1件ずつに展開して返す。"""
    user = _feed_user(token)
    events = _feed_events(user)
    start = logic.today()
    out = []
    for offset in range(60):
        day = start + timedelta(days=offset)
        for ev in events:
            if logic.event_occurs_on(ev, day):
                out.append(
                    {
                        "id": ev["id"],
                        "title": _feed_title(ev),
                        "date": day.isoformat(),
                        "start": ev["start_time"],
                        "end": ev["end_time"],
                        "memo": ev["memo"],
                        "kind": ev["kind"],
                    }
                )
    return jsonify(from_date=start.isoformat(), days=60, events=out)
