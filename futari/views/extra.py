"""タスク・予定（カレンダー）・在庫・生活メモ。"""
import calendar as pycal
from datetime import date, timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for

from .. import auth, logic, push
from ..db import get_db, now_iso
from . import back, bp, hh, text
from .daily import _member_or_none, add_shopping_item

# ---------- タスク ----------


@bp.route("/tasks")
@auth.login_required
def tasks():
    db = get_db()
    todo = db.all("select * from tasks where household_id = ? and done = 0", [hh()])
    todo.sort(key=lambda t: (t["due_date"] is None, t["due_date"] or "", t["created_at"]))
    today = logic.today().isoformat()
    for t in todo:
        t["overdue"] = bool(t["due_date"] and t["due_date"] < today)
    done = db.all(
        "select * from tasks where household_id = ? and done = 1 order by done_at desc limit 15", [hh()]
    )
    return render_template("tasks.html", todo=todo, done=done)


@bp.route("/tasks/add", methods=["POST"])
@auth.login_required
def task_add():
    title = text("title", 80)
    if not title:
        flash("やることを入力してください。", "error")
        return back("main.tasks")
    assignee = _member_or_none(request.form.get("assignee_id"))
    due = logic.parse_date(request.form.get("due_date"))
    get_db().insert(
        "tasks",
        household_id=hh(),
        title=title,
        assignee_id=assignee,
        due_date=due.isoformat() if due else None,
        memo=text("memo", 500),
        done=0,
        created_at=now_iso(),
    )
    if assignee and assignee != g.user["id"]:
        when = f"（{logic.fmt_day(due)}まで）" if due else ""
        push.notify([assignee], f"{g.user['display_name']}からお願い", f"{title}{when}", "/tasks")
    return back("main.tasks")


@bp.route("/tasks/<task_id>/toggle", methods=["POST"])
@auth.login_required
def task_toggle(task_id):
    db = get_db()
    task = db.one("select done from tasks where id = ? and household_id = ?", [task_id, hh()])
    if task:
        done = 0 if task["done"] else 1
        db.run(
            "update tasks set done = ?, done_by = ?, done_at = ? where id = ? and household_id = ?",
            [done, g.user["id"] if done else None, now_iso() if done else None, task_id, hh()],
        )
    return back("main.tasks")


@bp.route("/tasks/<task_id>/delete", methods=["POST"])
@auth.login_required
def task_delete(task_id):
    get_db().run("delete from tasks where id = ? and household_id = ?", [task_id, hh()])
    return back("main.tasks")


# ---------- 予定 ----------


def _own_event(event_id):
    """編集してよい予定（世帯の予定か、自分の予定）だけを返す。"""
    ev = get_db().one("select * from events where id = ? and household_id = ?", [event_id, hh()])
    if not ev or ev["owner_id"] not in (None, g.user["id"]):
        abort(404)
    return ev


def _hhmm(value):
    value = (value or "").strip()
    if len(value) == 5 and value[2] == ":" and value[:2].isdigit() and value[3:].isdigit():
        if int(value[:2]) < 24 and int(value[3:]) < 60:
            return value
    return ""


def _event_fields():
    kind = request.form.get("kind")
    if kind not in ("event", "anniversary", "garbage"):
        kind = "event"
    repeat = request.form.get("repeat_type")
    if repeat not in ("none", "weekly", "monthly", "yearly"):
        repeat = "none"
    scope = request.form.get("scope")
    visibility = request.form.get("visibility")
    if visibility not in ("private", "busy", "full"):
        visibility = "full"
    weekdays = ",".join(
        str(i) for i in sorted({int(x) for x in request.form.getlist("weekdays") if x.isdigit() and int(x) < 7})
    )
    if kind == "anniversary":
        repeat = "yearly"
    if kind == "garbage":
        repeat, scope = "weekly", "shared"
    day = logic.parse_date(request.form.get("day")) or logic.today()
    start = _hhmm(request.form.get("start_time"))
    end = _hhmm(request.form.get("end_time")) if start else ""
    return dict(
        title=text("title", 60),
        day=day.isoformat(),
        start_time=start,
        end_time=end,
        kind=kind,
        owner_id=None if scope == "shared" else g.user["id"],
        visibility=visibility,
        repeat_type=repeat,
        weekdays=weekdays if repeat == "weekly" else "",
        memo=text("memo", 500),
    )


@bp.route("/calendar")
@auth.login_required
def calendar():
    db = get_db()
    today = logic.today()
    selected = logic.parse_date(request.args.get("day")) or today
    try:
        year, month = (int(x) for x in request.args.get("month", "").split("-"))
        first = date(year, month, 1)
    except ValueError:
        first = selected.replace(day=1)
    if request.args.get("month") and not request.args.get("day"):
        selected = today if (today.year, today.month) == (first.year, first.month) else first
    events = db.all("select * from events where household_id = ?", [hh()])
    plain = [e for e in events if e["kind"] != "garbage"]
    weeks = []
    for week in pycal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month):
        row = []
        for d in week:
            marks = []
            for e in logic.events_on(plain, d, g.user["id"], g.names):
                marks.append("shared" if e["shared"] else e["owner_id"])
            row.append(dict(date=d, in_month=d.month == first.month, marks=marks[:3]))
        weeks.append(row)
    day_events = logic.events_on(events, selected, g.user["id"], g.names)
    for e in day_events:
        e["repeat_label"] = logic.event_repeat_label(e)
        e["editable"] = e["shared"] or e["mine"]
    garbage = [e for e in events if e["kind"] == "garbage"]
    for e in garbage:
        e["repeat_label"] = logic.event_repeat_label(e)
        e["weekday_list"] = logic.parse_weekdays(e["weekdays"])
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return render_template(
        "calendar.html",
        today=today,
        selected=selected,
        first=first,
        weeks=weeks,
        day_events=day_events,
        garbage=garbage,
        prev_month=prev_month.strftime("%Y-%m"),
        next_month=next_month.strftime("%Y-%m"),
    )


def _calendar_url(day_iso):
    return url_for("main.calendar", day=day_iso)


@bp.route("/calendar/save", methods=["POST"])
@auth.login_required
def event_save():
    db = get_db()
    f = _event_fields()
    if not f["title"]:
        flash("予定の名前を入力してください。", "error")
        return redirect(_calendar_url(f["day"]))
    if f["kind"] == "garbage" and not f["weekdays"]:
        flash("収集の曜日を1つ以上選んでください。", "error")
        return redirect(_calendar_url(f["day"]))
    event_id = request.form.get("id")
    if event_id:
        _own_event(event_id)
        cols = ", ".join(f"{k} = ?" for k in f)
        db.run(f"update events set {cols} where id = ? and household_id = ?", list(f.values()) + [event_id, hh()])
    else:
        db.insert("events", household_id=hh(), created_at=now_iso(), **f)
    return redirect(_calendar_url(request.form.get("return_day") or f["day"]))


@bp.route("/calendar/<event_id>/delete", methods=["POST"])
@auth.login_required
def event_delete(event_id):
    ev = _own_event(event_id)
    get_db().run("delete from events where id = ? and household_id = ?", [event_id, hh()])
    return redirect(_calendar_url(request.form.get("return_day") or ev["day"]))


# ---------- 在庫 ----------


@bp.route("/pantry")
@auth.login_required
def pantry():
    items = get_db().all("select * from pantry_items where household_id = ?", [hh()])
    items.sort(key=lambda i: (i["expires_on"] is None, i["expires_on"] or "", i["name"]))
    today = logic.today()
    for i in items:
        d = logic.parse_date(i["expires_on"])
        i["days_left"] = (d - today).days if d else None
    return render_template("pantry.html", items=items)


@bp.route("/pantry/add", methods=["POST"])
@auth.login_required
def pantry_add():
    name = text("name", 40)
    if not name:
        flash("食材の名前を入力してください。", "error")
        return back("main.pantry")
    expires = logic.parse_date(request.form.get("expires_on"))
    get_db().insert(
        "pantry_items",
        household_id=hh(),
        name=name,
        qty=text("qty", 20),
        expires_on=expires.isoformat() if expires else None,
        created_at=now_iso(),
    )
    return back("main.pantry")


@bp.route("/pantry/<item_id>/used", methods=["POST"])
@auth.login_required
def pantry_used(item_id):
    db = get_db()
    item = db.one("select * from pantry_items where id = ? and household_id = ?", [item_id, hh()])
    if item:
        db.run("delete from pantry_items where id = ?", [item_id])
        if request.form.get("rebuy") and add_shopping_item(db, item["name"]):
            flash(f"「{item['name']}」を買い物リストに追加しました。", "ok")
    return back("main.pantry")


# ---------- 生活メモ ----------


@bp.route("/notes")
@auth.login_required
def notes():
    rows = get_db().all("select * from notes where household_id = ? order by updated_at desc", [hh()])
    groups = []
    for key, label in logic.NOTE_CATEGORIES:
        items = [n for n in rows if n["category"] == key]
        if items:
            groups.append((label, items))
    return render_template("notes.html", groups=groups, categories=logic.NOTE_CATEGORIES)


@bp.route("/notes/save", methods=["POST"])
@auth.login_required
def note_save():
    db = get_db()
    title = text("title", 60)
    if not title:
        flash("メモのタイトルを入力してください。", "error")
        return back("main.notes")
    category = request.form.get("category")
    if category not in dict(logic.NOTE_CATEGORIES):
        category = "other"
    body = (request.form.get("body") or "").strip()[:5000]
    note_id = request.form.get("id")
    if note_id:
        db.run(
            "update notes set title = ?, body = ?, category = ?, updated_at = ? where id = ? and household_id = ?",
            [title, body, category, now_iso(), note_id, hh()],
        )
    else:
        db.insert("notes", household_id=hh(), title=title, body=body, category=category, updated_at=now_iso())
    return back("main.notes")


@bp.route("/notes/<note_id>/delete", methods=["POST"])
@auth.login_required
def note_delete(note_id):
    get_db().run("delete from notes where id = ? and household_id = ?", [note_id, hh()])
    return back("main.notes")
