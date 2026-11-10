"""Persistencia local en SQLite: caché (R, IA) y registro de correcciones enviadas."""
import json
import sqlite3
import time

from . import config

_SCHEMA = """
create table if not exists cache(key text primary key, value text, created real);
create table if not exists grades(
  id integer primary key, assignment_id int, user_id int, scores text, comment text,
  dry_run int, result text, created real);
"""


def _conn():
    config.DATA_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.executescript(_SCHEMA)
    return c


def cache_get(key):
    with _conn() as c:
        row = c.execute("select value from cache where key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_get_fresh(key, max_age):
    with _conn() as c:
        row = c.execute("select value, created from cache where key=?", (key,)).fetchone()
    return json.loads(row[0]) if row and time.time() - row[1] < max_age else None


def cache_set(key, value):
    with _conn() as c:
        c.execute("insert or replace into cache values(?,?,?)", (key, json.dumps(value), time.time()))


def log_grade(assignment_id, user_id, scores, comment, dry_run, result):
    with _conn() as c:
        c.execute("insert into grades(assignment_id,user_id,scores,comment,dry_run,result,created) "
                  "values(?,?,?,?,?,?,?)", (assignment_id, user_id, json.dumps(scores), comment,
                                            int(dry_run), json.dumps(result, default=str), time.time()))


def graded_by_app(assignment_id):
    """{user_id: último registro} de lo enviado desde la app."""
    with _conn() as c:
        rows = c.execute("select user_id, scores, comment, dry_run, created from grades "
                         "where assignment_id=? order by created", (assignment_id,)).fetchall()
    return {u: {"scores": json.loads(s), "comment": cm, "dry_run": bool(d), "at": t} for u, s, cm, d, t in rows}
