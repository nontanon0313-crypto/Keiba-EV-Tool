"""horse_details から血統インデックスを構築する。

pedigree_index テーブル: lineage_nb, name, sire, sire_sire, dam, dam_sire, dam_dam

使い方:
    python3 -m backend.scripts.build_pedigree_index
"""
import os
import json
import time
from datetime import datetime

import libsql_client

LOG_PATH = "pedigree_index.log"


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    t0 = time.time()
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS pedigree_index ("
            "lineage_nb TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "sire TEXT,"
            "sire_sire TEXT,"
            "dam TEXT,"
            "dam_sire TEXT,"
            "dam_dam TEXT,"
            "updated_at TEXT NOT NULL)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ped_sire ON pedigree_index(sire)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ped_damsire ON pedigree_index(dam_sire)")

        n_total = 0
        n_ok = 0
        last_ln = ""
        PAGE = 200
        stmts = []
        while True:
            r = c.execute(
                "SELECT lineage_nb, payload FROM horse_details WHERE lineage_nb > ? ORDER BY lineage_nb LIMIT ?",
                [last_ln, PAGE],
            )
            rows = list(r.rows)
            if not rows:
                break
            for row in rows:
                n_total += 1
                ln = row[0]
                try:
                    d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                except Exception:
                    continue
                pg = d.get("pedigree") or {}
                name = ""
                t = d.get("title") or ""
                if t:
                    name = t.split("の成績")[0]
                if not name:
                    continue
                now = datetime.now().isoformat()
                stmts.append((
                    "INSERT INTO pedigree_index (lineage_nb, name, sire, sire_sire, dam, dam_sire, dam_dam, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT (lineage_nb) DO UPDATE SET "
                    "name=EXCLUDED.name, sire=EXCLUDED.sire, sire_sire=EXCLUDED.sire_sire, "
                    "dam=EXCLUDED.dam, dam_sire=EXCLUDED.dam_sire, dam_dam=EXCLUDED.dam_dam, updated_at=EXCLUDED.updated_at",
                    [ln, name, pg.get("sire") or "", pg.get("sire_sire") or "",
                     pg.get("dam") or "", pg.get("dam_sire") or "", pg.get("dam_dam") or "", now],
                ))
                n_ok += 1
            last_ln = rows[-1][0]
            if len(stmts) >= 200:
                try:
                    c.batch(stmts)
                except Exception as exc:
                    _log("batch fail: " + repr(exc))
                stmts = []
            if len(rows) < PAGE:
                break
            if n_total % 3000 == 0:
                _log("  処理: " + str(n_total) + "件 (ok=" + str(n_ok) + ")")
        if stmts:
            try:
                c.batch(stmts)
            except Exception as exc:
                _log("final batch fail: " + repr(exc))
        _log("DONE total=" + str(n_total) + " ok=" + str(n_ok) + " " + str(round(time.time() - t0, 1)) + "s")
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
