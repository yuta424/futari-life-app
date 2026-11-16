"""Web Push（iPhone ではホーム画面に追加した PWA で受信できる）。"""
import json
import logging

from flask import current_app

from .db import get_db

log = logging.getLogger(__name__)


def push_enabled():
    cfg = current_app.config
    return bool(cfg.get("VAPID_PUBLIC_KEY") and cfg.get("VAPID_PRIVATE_KEY"))


def _send(sub, payload):
    """1件送信。戻り値: 'ok' / 'gone'（購読が無効）/ 'error'。"""
    from pywebpush import WebPushException, webpush

    cfg = current_app.config
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=cfg["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": cfg.get("VAPID_SUBJECT") or "mailto:admin@example.com"},
            ttl=60 * 60 * 12,
            timeout=8,
        )
        return "ok"
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        log.warning("push failed: %s", e)
        return "error"
    except Exception as e:  # 通知の失敗でアプリの操作を止めない
        log.warning("push failed: %s", e)
        return "error"


def notify(user_ids, title, body, url="/"):
    """指定ユーザーの全端末に通知する。送れた件数を返す。"""
    user_ids = [u for u in user_ids if u]
    if not user_ids or not push_enabled():
        return 0
    db = get_db()
    marks = ", ".join("?" for _ in user_ids)
    subs = db.all(f"select * from push_subscriptions where user_id in ({marks})", user_ids)
    sent = 0
    for sub in subs:
        result = _send(sub, {"title": title, "body": body, "url": url})
        if result == "ok":
            sent += 1
        elif result == "gone":
            db.run("delete from push_subscriptions where id = ?", [sub["id"]])
    return sent
