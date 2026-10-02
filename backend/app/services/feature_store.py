"""全レース×全馬の特徴量を保存する Turso ストア。"""
import os
import json
from datetime import datetime


def _turso_creds():
    u = os.getenv("TURSO_URL")
    t = os.getenv("TURSO_TOKEN")
    if u and t:
        return u, t
    return None, None


class _Turso:
    name = "turso"

    def __init__(self):
        from backend.app.services import turso_client
        client, err = turso_client.get_client()
        if client is None:
            raise RuntimeError("turso_client: " + str(err))
        self.client = client
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS features ("
            "race_id TEXT NOT NULL,"
            "horse_number INTEGER NOT NULL,"
            "lineage_nb TEXT,"
            "features_json TEXT NOT NULL,"
            "computed_at TEXT NOT NULL,"
            "PRIMARY KEY (race_id, horse_number))"
        )
        self.client.execute(
            "CREATE INDEX IF NOT EXISTS idx_features_lineage ON features(lineage_nb)"
        )

    def upsert_batch(self, rows):
        """rows: [(race_id, horse_number, lineage_nb, features_dict), ...]"""
        if not rows:
            return 0
        now = datetime.now().isoformat()
        stmts = []
        for (rid, num, ln, feats) in rows:
            pj = json.dumps(feats, ensure_ascii=False)
            stmts.append((
                "INSERT INTO features (race_id, horse_number, lineage_nb, features_json, computed_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT (race_id, horse_number) DO UPDATE SET "
                "lineage_nb=EXCLUDED.lineage_nb, features_json=EXCLUDED.features_json, computed_at=EXCLUDED.computed_at",
                [rid, int(num), str(ln or ""), pj, now],
            ))
        self.client.batch(stmts)
        return len(stmts)

    def count(self):
        r = self.client.execute("SELECT COUNT(*) FROM features")
        return r.rows[0][0] if r.rows else 0

    def races_done(self):
        """既に特徴量が計算済みの race_id 集合を返す。"""
        r = self.client.execute("SELECT DISTINCT race_id FROM features")
        return set(row[0] for row in r.rows if row[0])


_backend = None


def _get():
    global _backend
    if _backend is not None:
        return _backend
    u, t = _turso_creds()
    if u and t:
        _backend = _Turso()
    else:
        raise RuntimeError("TURSO_URL/TURSO_TOKEN not set")
    return _backend


def upsert_batch(rows):
    return _get().upsert_batch(rows)


def count():
    return _get().count()


def races_done():
    return _get().races_done()
