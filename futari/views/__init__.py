from flask import Blueprint, g, redirect, request, url_for

bp = Blueprint("main", __name__)


def hh():
    return g.user["household_id"]


def back(endpoint, **kwargs):
    """操作のあと元の画面へ戻る。フォームの _next（アプリ内パスのみ）を優先。"""
    nxt = request.form.get("_next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for(endpoint, **kwargs))


def text(name, limit=200):
    return (request.form.get(name) or "").strip()[:limit]


from . import core, daily, extra  # noqa: E402,F401
