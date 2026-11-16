"""データベース接続。本番は Supabase (PostgreSQL)、ローカルは SQLite。

SQL は両方で動く書き方だけを使い、プレースホルダは `?` で統一する。
"""
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "supabase", "schema.sql")
PG_ONLY_MARKER = "-- [postgres-only]"


def new_id():
    return uuid.uuid4().hex


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, url):
        self.is_pg = url.startswith(("postgres://", "postgresql://"))
        if self.is_pg:
            import psycopg2
            import psycopg2.extras

            if "sslmode=" not in url:
                url += ("&" if "?" in url else "?") + "sslmode=require"
            self.conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
        else:
            path = url.replace("sqlite:///", "", 1)
            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("pragma foreign_keys = on")

    def execute(self, sql, params=()):
        if self.is_pg:
            sql = sql.replace("%", "%%").replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def all(self, sql, params=()):
        return [dict(r) for r in self.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def run(self, sql, params=()):
        return self.execute(sql, params).rowcount

    def insert(self, table, **values):
        values.setdefault("id", new_id())
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        self.execute(f"insert into {table} ({cols}) values ({marks})", list(values.values()))
        return values["id"]

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    if "db" not in g:
        g.db = DB(current_app.config["DATABASE_URL"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is None:
        return
    try:
        if exc is None:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()


def init_sqlite(url):
    """ローカル用: SQLite に schema.sql（Postgres 専用部分を除く）を流す。"""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sql = f.read().split(PG_ONLY_MARKER)[0]
    db = DB(url)
    db.conn.executescript(sql)
    db.commit()
    db.close()
