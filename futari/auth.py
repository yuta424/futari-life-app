"""ログイン。本番は Supabase Auth（メール＋パスワード / Google）。

SUPABASE_URL が未設定のときだけ、開発用にローカルのパスワード認証を使う。
"""
import base64
import hashlib
import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import abort, current_app, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, new_id, now_iso


class AuthError(Exception):
    pass


def supabase_enabled():
    return bool(current_app.config.get("SUPABASE_URL"))


def _sb(path, payload):
    cfg = current_app.config
    try:
        r = requests.post(
            cfg["SUPABASE_URL"].rstrip("/") + "/auth/v1" + path,
            json=payload,
            headers={"apikey": cfg["SUPABASE_ANON_KEY"], "Content-Type": "application/json"},
            timeout=10,
        )
    except requests.RequestException as e:
        raise AuthError("ログインサーバーに接続できませんでした。時間をおいて試してください。") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        raise AuthError(_translate(data))
    return data


def _translate(data):
    code = (data.get("error_code") or data.get("code") or "") if isinstance(data, dict) else ""
    msg = (data.get("msg") or data.get("error_description") or data.get("message") or "") if isinstance(data, dict) else ""
    table = {
        "invalid_credentials": "メールアドレスかパスワードが違います。",
        "email_not_confirmed": "メールアドレスの確認がまだです。届いたメールのリンクを開いてください。",
        "user_already_exists": "このメールアドレスは登録済みです。ログインしてください。",
        "weak_password": "パスワードが短すぎます。6文字以上にしてください。",
        "over_email_send_rate_limit": "確認メールの送信回数が上限に達しました。しばらく待ってください。",
        "signup_disabled": "新規登録は現在停止されています。",
    }
    return table.get(str(code), msg or "ログインに失敗しました。")


def _upsert_user(uid, email):
    db = get_db()
    user = db.one("select * from users where id = ?", [uid])
    if user:
        return user
    db.insert(
        "users",
        id=uid,
        email=email,
        display_name="",
        color="anzu",
        ical_token=secrets.token_urlsafe(24),
        created_at=now_iso(),
    )
    return db.one("select * from users where id = ?", [uid])


def start_session(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(24)


def sign_up(email, password):
    """戻り値: user（すぐログインできる場合）か None（確認メール待ち）。"""
    if len(password) < 6:
        raise AuthError("パスワードは6文字以上にしてください。")
    if supabase_enabled():
        data = _sb("/signup", {"email": email, "password": password})
        user = data.get("user") or data
        if not data.get("access_token"):
            # 確認メール待ち。登録済みアドレスのときも Supabase は同じ応答を返す。
            return None
        return _upsert_user(user["id"], user.get("email") or email)
    db = get_db()
    if db.one("select id from users where email = ?", [email]):
        raise AuthError("このメールアドレスは登録済みです。ログインしてください。")
    uid = new_id()
    user = _upsert_user(uid, email)
    db.run("update users set password_hash = ? where id = ?", [generate_password_hash(password), uid])
    return user


def sign_in(email, password):
    if supabase_enabled():
        data = _sb("/token?grant_type=password", {"email": email, "password": password})
        user = data["user"]
        return _upsert_user(user["id"], user.get("email") or email)
    user = get_db().one("select * from users where email = ?", [email])
    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        raise AuthError("メールアドレスかパスワードが違います。")
    return user


def google_authorize_url(callback_url):
    verifier = secrets.token_urlsafe(48)
    session["pkce"] = verifier
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    qs = urlencode(
        {
            "provider": "google",
            "redirect_to": callback_url,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        }
    )
    return current_app.config["SUPABASE_URL"].rstrip("/") + "/auth/v1/authorize?" + qs


def google_finish(code):
    verifier = session.pop("pkce", None)
    if not verifier:
        raise AuthError("ログインの有効期限が切れました。もう一度お試しください。")
    data = _sb("/token?grant_type=pkce", {"auth_code": code, "code_verifier": verifier})
    user = data["user"]
    return _upsert_user(user["id"], user.get("email") or "")


def load_user():
    g.user = None
    g.members = []
    g.names = {}
    uid = session.get("uid")
    if not uid:
        return
    db = get_db()
    user = db.one("select * from users where id = ?", [uid])
    if not user:
        session.clear()
        return
    g.user = user
    if user["household_id"]:
        g.members = db.all(
            "select id, display_name, color, email from users where household_id = ? order by created_at, id",
            [user["household_id"]],
        )
        g.names = {m["id"]: m["display_name"] for m in g.members}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("main.login"))
        if not g.user["household_id"] or not g.user["display_name"]:
            return redirect(url_for("main.welcome"))
        return view(*args, **kwargs)

    return wrapped


def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("csrf") or ""
    if not expected or not secrets.compare_digest(sent, expected):
        abort(400, description="ページの有効期限が切れました。前の画面に戻って、もう一度お試しください。")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]
