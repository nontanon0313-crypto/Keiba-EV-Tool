"""ストレージ抽象。優先順: Postgres -> Turso -> file。"""
import os
import json
from pathlib import Path
from urllib.parse import urlparse

FILE_PATH = Path("bets.json")

PG_ENV_KEYS = [
    "DATABASE_URL",
    "NEON_DATABASE_URL",
    "SUPABASE_DATABASE_URL",
    "AIVEN_DATABASE_URL",
    "COCKROACH_DATABASE_URL",
]


def pg_url():
    for k in PG_ENV_KEYS:
        v = os.getenv(k)
        if v:
            return v
    return None


def turso_creds():
    u = os.getenv("TURSO_URL")
    t = os.getenv("TURSO_TOKEN")
    if u and t:
        return u, t
    return None, None


def detect_backend():
    if pg_url():
        return "postgres"
    u, _ = turso_creds()
    if u:
        return "turso"
    return "file"


class FileStorage:
    name = "file"

    def load_all(self):
        if not FILE_PATH.exists():
            return []
        try:
            return json.loads(FILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save_all(self, items):
        FILE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_pg(url):
    u = urlparse(url)
    return {
        "user": u.username,
        "password": u.password,
        "host": u.hostname,
        "port": u.port or 5432,
        "database": (u.path or "/").lstrip("/") or "postgres",
    }


class PostgresStorage:
    name = "postgres"

    def __init__(self, url):
        import pg8000.dbapi
        self._dbapi = pg8000.dbapi
        self._params = _parse_pg(url)
        self._ensure_schema()

    def _conn(self):
        return self._dbapi.connect(**self._params)

    def _ensure_schema(self):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bets (
                    id BIGSERIAL PRIMARY KEY,
                    race_id TEXT NOT NULL,
                    combo TEXT NOT NULL,
                    amount INT NOT NULL,
                    odds DOUBLE PRECISION NOT NULL,
                    prob DOUBLE PRECISION,
                    ev DOUBLE PRECISION,
                    ticket_type TEXT DEFAULT 'trifecta',
                    payout INT,
                    created_at TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def load_all(self):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, race_id, combo, amount, odds, prob, ev, ticket_type, payout, created_at FROM bets ORDER BY id")
            rows = cur.fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            out.append({
                "id": int(r[0]),
                "race_id": r[1],
                "combo": r[2],
                "amount": int(r[3]),
                "odds": float(r[4]),
                "prob": float(r[5]) if r[5] is not None else None,
                "ev": float(r[6]) if r[6] is not None else None,
                "ticket_type": r[7] or "trifecta",
                "payout": int(r[8]) if r[8] is not None else None,
                "created_at": r[9] or "",
            })
        return out

    def save_all(self, items):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM bets")
            for it in items:
                cur.execute(
                    "INSERT INTO bets (id, race_id, combo, amount, odds, prob, ev, ticket_type, payout, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (it.get("id"), it["race_id"], it["combo"], int(it["amount"]), float(it["odds"]),
                     it.get("prob"), it.get("ev"), it.get("ticket_type", "trifecta"),
                     it.get("payout"), it.get("created_at", "")),
                )
            conn.commit()
        finally:
            conn.close()


class TursoStorage:
    name = "turso"

    def __init__(self, url, token):
        import libsql_client
        # libsql:// -> https:// に変換 (WebSocketではなくHTTP接続を使う)
        http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
        self.client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        self._ensure_schema()

    def _ensure_schema(self):
        self.client.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                combo TEXT NOT NULL,
                amount INTEGER NOT NULL,
                odds REAL NOT NULL,
                prob REAL,
                ev REAL,
                ticket_type TEXT DEFAULT 'trifecta',
                payout INTEGER,
                created_at TEXT
            )
        """)

    def load_all(self):
        r = self.client.execute("SELECT id, race_id, combo, amount, odds, prob, ev, ticket_type, payout, created_at FROM bets ORDER BY id")
        out = []
        for row in r.rows:
            out.append({
                "id": int(row[0]),
                "race_id": row[1],
                "combo": row[2],
                "amount": int(row[3]),
                "odds": float(row[4]),
                "prob": float(row[5]) if row[5] is not None else None,
                "ev": float(row[6]) if row[6] is not None else None,
                "ticket_type": row[7] or "trifecta",
                "payout": int(row[8]) if row[8] is not None else None,
                "created_at": row[9] or "",
            })
        return out

    def save_all(self, items):
        self.client.execute("DELETE FROM bets")
        for it in items:
            self.client.execute(
                "INSERT INTO bets (id, race_id, combo, amount, odds, prob, ev, ticket_type, payout, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [it.get("id"), it["race_id"], it["combo"], int(it["amount"]), float(it["odds"]),
                 it.get("prob"), it.get("ev"), it.get("ticket_type", "trifecta"),
                 it.get("payout"), it.get("created_at", "")],
            )


_storage = None


def get_storage():
    global _storage
    if _storage is not None:
        return _storage
    mode = detect_backend()
    if mode == "postgres":
        try:
            _storage = PostgresStorage(pg_url())
            print("[storage] backend=postgres")
            return _storage
        except Exception as e:
            print("[storage] postgres init failed, fallback:", e)
    if mode == "turso":
        try:
            u, t = turso_creds()
            _storage = TursoStorage(u, t)
            print("[storage] backend=turso")
            return _storage
        except Exception as e:
            print("[storage] turso init failed, fallback:", e)
    _storage = FileStorage()
    print("[storage] backend=file")
    return _storage
