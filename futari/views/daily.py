"""家事・買い物リスト・献立・レシピ。"""
from datetime import timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for

from .. import auth, logic, push
from ..db import get_db, now_iso
from . import back, bp, hh, text
from .core import _chores_for


def _member_or_none(value):
    return value if value in g.names else None


# ---------- 家事 ----------


def _chore_fields():
    freq = request.form.get("freq_type")
    if freq not in ("daily", "weekly", "interval"):
        freq = "daily"
    weekdays = ",".join(str(i) for i in sorted({int(x) for x in request.form.getlist("weekdays") if x.isdigit() and int(x) < 7}))
    try:
        interval = min(365, max(1, int(request.form.get("interval_days") or 1)))
    except ValueError:
        interval = 1
    return dict(
        name=text("name", 40),
        freq_type=freq,
        weekdays=weekdays,
        interval_days=interval,
        assignee_id=_member_or_none(request.form.get("assignee_id")),
    )


@bp.route("/chores")
@auth.login_required
def chores():
    db = get_db()
    day = logic.today()
    todays = _chores_for(db, hh(), day)
    todays.sort(key=lambda c: c["log"] is not None)
    all_chores = db.all("select * from chores where household_id = ? and active = 1 order by created_at", [hh()])
    for c in all_chores:
        c["freq_label"] = logic.chore_freq_label(c)
        c["weekday_list"] = logic.parse_weekdays(c["weekdays"])
    since = (day - timedelta(days=29)).isoformat()
    counts = {
        r["done_by"]: r["n"]
        for r in db.all(
            "select done_by, count(*) as n from chore_logs where household_id = ? and due_date >= ? group by done_by",
            [hh(), since],
        )
    }
    total = sum(counts.values())
    balance = [
        dict(member=m, count=counts.get(m["id"], 0), pct=round(counts.get(m["id"], 0) * 100 / total) if total else 0)
        for m in g.members
    ]
    return render_template("chores.html", day=day, todays=todays, all_chores=all_chores, balance=balance, total=total)


@bp.route("/chores/add", methods=["POST"])
@auth.login_required
def chore_add():
    f = _chore_fields()
    if not f["name"]:
        flash("家事の名前を入力してください。", "error")
    elif f["freq_type"] == "weekly" and not f["weekdays"]:
        flash("曜日を1つ以上選んでください。", "error")
    else:
        get_db().insert(
            "chores", household_id=hh(), start_date=logic.today().isoformat(), active=1, created_at=now_iso(), **f
        )
    return back("main.chores")


@bp.route("/chores/<chore_id>/edit", methods=["POST"])
@auth.login_required
def chore_edit(chore_id):
    f = _chore_fields()
    if not f["name"] or (f["freq_type"] == "weekly" and not f["weekdays"]):
        flash("名前と曜日を確認してください。", "error")
    else:
        get_db().run(
            "update chores set name = ?, freq_type = ?, weekdays = ?, interval_days = ?, assignee_id = ?"
            " where id = ? and household_id = ?",
            [f["name"], f["freq_type"], f["weekdays"], f["interval_days"], f["assignee_id"], chore_id, hh()],
        )
    return back("main.chores")


@bp.route("/chores/<chore_id>/delete", methods=["POST"])
@auth.login_required
def chore_delete(chore_id):
    # 記録（誰がいつやったか）は残したいので、削除ではなく非表示にする
    get_db().run("update chores set active = 0 where id = ? and household_id = ?", [chore_id, hh()])
    return back("main.chores")


@bp.route("/chores/<chore_id>/toggle", methods=["POST"])
@auth.login_required
def chore_toggle(chore_id):
    db = get_db()
    chore = db.one("select id from chores where id = ? and household_id = ?", [chore_id, hh()])
    if chore:
        day = (logic.parse_date(request.form.get("day")) or logic.today()).isoformat()
        deleted = db.run("delete from chore_logs where chore_id = ? and due_date = ?", [chore_id, day])
        if not deleted:
            db.insert(
                "chore_logs",
                chore_id=chore_id,
                household_id=hh(),
                due_date=day,
                done_by=g.user["id"],
                done_at=now_iso(),
            )
    return back("main.chores")


# ---------- 買い物リスト ----------


def _shopping_context():
    db = get_db()
    items = db.all("select * from shopping_items where household_id = ? order by created_at", [hh()])
    todo = [i for i in items if not i["done"]]
    done = sorted((i for i in items if i["done"]), key=lambda i: i["done_at"] or "", reverse=True)
    groups = []
    for key, label in logic.SHOP_CATEGORIES:
        rows = [i for i in todo if i["category"] == key]
        if rows:
            groups.append((label, rows))
    known = {i["name"] for i in todo}
    suggestions = []
    for i in done:
        if i["name"] not in known and i["name"] not in suggestions:
            suggestions.append(i["name"])
    return dict(groups=groups, todo_count=len(todo), done=done[:30], suggestions=suggestions[:12])


@bp.route("/shopping")
@auth.login_required
def shopping():
    return render_template("shopping.html", categories=logic.SHOP_CATEGORIES, **_shopping_context())


def add_shopping_item(db, name, qty="", meal_id=None, category=None):
    """未購入に同じ名前があれば追加しない。追加したら True。"""
    name = name.strip()[:40]
    if not name:
        return False
    if db.one("select id from shopping_items where household_id = ? and done = 0 and name = ?", [hh(), name]):
        return False
    db.insert(
        "shopping_items",
        household_id=hh(),
        name=name,
        qty=qty.strip()[:20],
        category=category or logic.guess_category(name),
        done=0,
        added_by=g.user["id"],
        meal_id=meal_id,
        created_at=now_iso(),
    )
    return True


@bp.route("/shopping/add", methods=["POST"])
@auth.login_required
def shopping_add():
    name = text("name", 40)
    if name and not add_shopping_item(get_db(), name, text("qty", 20)):
        flash(f"「{name}」はすでにリストにあります。", "info")
    return back("main.shopping")


@bp.route("/shopping/<item_id>/toggle", methods=["POST"])
@auth.login_required
def shopping_toggle(item_id):
    db = get_db()
    item = db.one("select done from shopping_items where id = ? and household_id = ?", [item_id, hh()])
    if item:
        done = 0 if item["done"] else 1
        db.run(
            "update shopping_items set done = ?, done_at = ? where id = ? and household_id = ?",
            [done, now_iso() if done else None, item_id, hh()],
        )
    return back("main.shopping")


@bp.route("/shopping/<item_id>/category", methods=["POST"])
@auth.login_required
def shopping_category(item_id):
    category = request.form.get("category")
    if category in logic.SHOP_CATEGORY_LABEL:
        get_db().run(
            "update shopping_items set category = ? where id = ? and household_id = ?", [category, item_id, hh()]
        )
    return back("main.shopping")


@bp.route("/shopping/<item_id>/delete", methods=["POST"])
@auth.login_required
def shopping_delete(item_id):
    get_db().run("delete from shopping_items where id = ? and household_id = ?", [item_id, hh()])
    return back("main.shopping")


@bp.route("/shopping/clear-done", methods=["POST"])
@auth.login_required
def shopping_clear_done():
    get_db().run("delete from shopping_items where household_id = ? and done = 1", [hh()])
    return back("main.shopping")


@bp.route("/shopping/notify", methods=["POST"])
@auth.login_required
def shopping_notify():
    db = get_db()
    items = db.all(
        "select name from shopping_items where household_id = ? and done = 0 order by created_at", [hh()]
    )
    partners = [m["id"] for m in g.members if m["id"] != g.user["id"]]
    if not items:
        flash("リストが空です。", "info")
    elif not partners:
        flash("まだ相手が参加していません。設定から招待コードを伝えてください。", "info")
    else:
        body = "、".join(i["name"] for i in items[:8]) + (" ほか" if len(items) > 8 else "")
        sent = push.notify(partners, f"{g.user['display_name']}から買い物リスト（{len(items)}件）", body, "/shopping")
        if sent:
            flash("相手に通知しました。", "ok")
        else:
            flash("相手の端末で通知がオンになっていないため、送れませんでした。", "info")
    return back("main.shopping")


# ---------- 献立 ----------


@bp.route("/meals")
@auth.login_required
def meals():
    db = get_db()
    today = logic.today()
    start = logic.week_start(logic.parse_date(request.args.get("week")) or today)
    days = [start + timedelta(days=i) for i in range(7)]
    rows = db.all(
        "select m.*, r.ingredients as recipe_ingredients, r.url as recipe_url from meals m"
        " left join recipes r on r.id = m.recipe_id"
        " where m.household_id = ? and m.day >= ? and m.day <= ?",
        [hh(), days[0].isoformat(), days[-1].isoformat()],
    )
    by_key = {(r["day"], r["slot"]): r for r in rows}
    recipes = db.all("select id, name from recipes where household_id = ? order by name", [hh()])
    return render_template(
        "meals.html",
        days=days,
        today=today,
        slots=logic.MEAL_SLOTS,
        by_key=by_key,
        recipes=recipes,
        prev_week=(start - timedelta(days=7)).isoformat(),
        next_week=(start + timedelta(days=7)).isoformat(),
        this_week=logic.week_start(today) == start,
    )


@bp.route("/meals/set", methods=["POST"])
@auth.login_required
def meal_set():
    db = get_db()
    day = logic.parse_date(request.form.get("day"))
    slot = request.form.get("slot")
    if day is None or slot not in dict(logic.MEAL_SLOTS):
        return back("main.meals")
    title = text("title", 60)
    week = logic.week_start(day).isoformat()
    if not title:
        db.run("delete from meals where household_id = ? and day = ? and slot = ?", [hh(), day.isoformat(), slot])
        return redirect(url_for("main.meals", week=week) + f"#d{day.isoformat()}")
    recipe = db.one("select id from recipes where household_id = ? and name = ?", [hh(), title])
    recipe_id = recipe["id"] if recipe else None
    existing = db.one(
        "select id from meals where household_id = ? and day = ? and slot = ?", [hh(), day.isoformat(), slot]
    )
    if existing:
        db.run("update meals set title = ?, recipe_id = ? where id = ?", [title, recipe_id, existing["id"]])
    else:
        db.insert("meals", household_id=hh(), day=day.isoformat(), slot=slot, title=title, recipe_id=recipe_id)
    return redirect(url_for("main.meals", week=week) + f"#d{day.isoformat()}")


@bp.route("/meals/<meal_id>/to-shopping", methods=["POST"])
@auth.login_required
def meal_to_shopping(meal_id):
    db = get_db()
    meal = db.one(
        "select m.*, r.ingredients from meals m join recipes r on r.id = m.recipe_id"
        " where m.id = ? and m.household_id = ?",
        [meal_id, hh()],
    )
    if not meal:
        flash("この献立にはレシピの材料が登録されていません。", "info")
        return back("main.meals")
    added = 0
    for line in meal["ingredients"].splitlines():
        # 「玉ねぎ 2個」のように、最初の空白までを品名、残りを数量として扱う
        parts = line.replace("　", " ").strip().split(None, 1)
        if parts and add_shopping_item(db, parts[0], parts[1] if len(parts) > 1 else "", meal_id=meal_id):
            added += 1
    if added:
        flash(f"{meal['title']}の材料を{added}件、買い物リストに追加しました。", "ok")
    else:
        flash("材料はすべてリストに入っています。", "info")
    week = logic.week_start(logic.parse_date(meal["day"]) or logic.today()).isoformat()
    return redirect(url_for("main.meals", week=week) + f"#d{meal['day']}")


# ---------- レシピ ----------


def _safe_url(url):
    return url if url.startswith(("https://", "http://")) else ""


@bp.route("/recipes")
@auth.login_required
def recipes():
    rows = get_db().all("select * from recipes where household_id = ? order by name", [hh()])
    return render_template("recipes.html", recipes=rows)


@bp.route("/recipes/save", methods=["POST"])
@auth.login_required
def recipe_save():
    db = get_db()
    name = text("name", 60)
    if not name:
        flash("料理名を入力してください。", "error")
        return back("main.recipes")
    fields = [name, _safe_url(text("url", 500)), text("ingredients", 2000), text("memo", 2000)]
    recipe_id = request.form.get("id")
    if recipe_id:
        if not db.one("select id from recipes where id = ? and household_id = ?", [recipe_id, hh()]):
            abort(404)
        db.run(
            "update recipes set name = ?, url = ?, ingredients = ?, memo = ? where id = ? and household_id = ?",
            fields + [recipe_id, hh()],
        )
    else:
        recipe_id = db.insert(
            "recipes",
            household_id=hh(),
            name=name,
            url=fields[1],
            ingredients=fields[2],
            memo=fields[3],
            created_at=now_iso(),
        )
    # 同じ名前で先に入れていた献立にも、このレシピをひも付ける
    db.run(
        "update meals set recipe_id = ? where household_id = ? and title = ? and recipe_id is null",
        [recipe_id, hh(), name],
    )
    return back("main.recipes")


@bp.route("/recipes/<recipe_id>/delete", methods=["POST"])
@auth.login_required
def recipe_delete(recipe_id):
    db = get_db()
    db.run("update meals set recipe_id = null where recipe_id = ? and household_id = ?", [recipe_id, hh()])
    db.run("delete from recipes where id = ? and household_id = ?", [recipe_id, hh()])
    return back("main.recipes")
