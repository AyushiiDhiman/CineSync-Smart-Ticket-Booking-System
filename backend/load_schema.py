"""
One-time loader: runs schema.sql on the database named in the DB_* env vars.
Put this file in the backend/ folder, next to schema.sql, then run:  python load_schema.py
Handles DELIMITER blocks (triggers / stored procedures) and skips the
CREATE DATABASE / USE lines, since hosted MySQL gives you a database already.
"""
import os
import re
import mysql.connector

conn = mysql.connector.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=os.environ["DB_NAME"],
    ssl_disabled=False,
)


def split_sql(text):
    statements, delim, buf = [], ";", []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^DELIMITER\s+(\S+)$", s, re.I)
        if m:
            delim = m.group(1)
            continue
        if re.match(r"^(CREATE DATABASE|USE)\b", s, re.I):
            continue
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(delim):
            stmt = "\n".join(buf).rstrip()
            stmt = stmt[: -len(delim)].rstrip()
            if stmt:
                statements.append(stmt)
            buf = []
    return statements


here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "schema.sql"), encoding="utf-8") as f:
    stmts = split_sql(f.read())

cur = conn.cursor()
ok = 0
for i, st in enumerate(stmts, 1):
    try:
        cur.execute(st)
        ok += 1
    except mysql.connector.Error as e:
        print(f"Statement {i} failed: {e}\n  {st[:120]!r}\n")
conn.commit()
print(f"Done: {ok}/{len(stmts)} statements ran.")
cur.close()
conn.close()
