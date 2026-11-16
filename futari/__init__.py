import os
from datetime import timedelta

from flask import Flask, g, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import auth, db, logic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(config=None):
    app = Flask(
        __name__,
        static_folder=os.path.join(ROOT, "public", "static"),
        static_url_path="/static",
    )
    env = os.environ
    app.config.update(
        DATABASE_URL=env.get("DATABASE_URL") or "sqlite:///" + os.path.join(ROOT, "local.db"),
        SECRET_KEY=env.get("SECRET_KEY"),
        SUPABASE_URL=env.get("SUPABASE_URL", ""),
        SUPABASE_ANON_KEY=env.get("SUPABASE_ANON_KEY", ""),
        VAPID_PUBLIC_KEY=env.get("VAPID_PUBLIC_KEY", ""),
        VAPID_PRIVATE_KEY=env.get("VAPID_PRIVATE_KEY", ""),
        VAPID_SUBJECT=env.get("VAPID_SUBJECT", ""),
        CRON_SECRET=env.get("CRON_SECRET", ""),
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if config:
        app.config.update(config)

    is_pg = app.config["DATABASE_URL"].startswith(("postgres://", "postgresql://"))
    if not app.config["SECRET_KEY"]:
        if is_pg:
            raise RuntimeError("SECRET_KEY が設定されていません。Vercel の環境変数に追加してください。")
        app.config["SECRET_KEY"] = "dev-only-secret"
    if is_pg:
        app.config["SESSION_COOKIE_SECURE"] = True
        if not app.config["SUPABASE_URL"]:
            raise RuntimeError("SUPABASE_URL が設定されていません（本番では Supabase Auth が必須です）。")
    else:
        db.init_sqlite(app.config["DATABASE_URL"])

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.teardown_appcontext(db.close_db)
    app.before_request(auth.load_user)
    app.before_request(auth.check_csrf)

    asset_version = (env.get("VERCEL_GIT_COMMIT_SHA") or "dev")[:8]

    @app.context_processor
    def inject():
        me = g.get("user")
        colors = {m["id"]: logic.COLORS.get(m["color"], logic.COLORS["anzu"])[1] for m in g.get("members", [])}
        def shopping_badge():
            if not me or not me["household_id"]:
                return 0
            if "shopping_badge" not in g:
                g.shopping_badge = db.get_db().one(
                    "select count(*) as n from shopping_items where household_id = ? and done = 0",
                    [me["household_id"]],
                )["n"]
            return g.shopping_badge

        return dict(
            shopping_badge=shopping_badge,
            csrf_token=auth.csrf_token,
            me=me,
            members=g.get("members", []),
            names=g.get("names", {}),
            member_colors=colors,
            fmt_day=logic.fmt_day,
            fmt_relative=logic.fmt_relative,
            COLORS=logic.COLORS,
            WEEKDAYS_JA=logic.WEEKDAYS_JA,
            asset_version=asset_version,
            supabase_enabled=bool(app.config["SUPABASE_URL"]),
            vapid_public_key=app.config["VAPID_PUBLIC_KEY"],
        )

    @app.errorhandler(400)
    @app.errorhandler(404)
    def friendly_error(e):
        title = "ページが見つかりません" if e.code == 404 else "うまくいきませんでした"
        detail = e.description if e.code == 400 else "URLが変わったか、削除された可能性があります。"
        return render_template("error.html", title=title, detail=detail), e.code

    from .views import bp

    app.register_blueprint(bp)
    return app
