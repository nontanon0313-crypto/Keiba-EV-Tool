"""馬連・ワイド・馬単の結果を Turso に保存。"""
import os
import json
from datetime import datetime

import libsql_client


TICKETS = ["quinella", "wide", "exacta", "trio", "trifecta"]


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    client.execute(
        "CREATE TABLE IF NOT EXISTS analytics_multi_cache ("
        "ticket TEXT PRIMARY KEY,"
        "payload TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )

    for ticket in TICKETS:
        path = f"scratch/multi_{ticket}_result.json"
        if not os.path.exists(path):
            print(f"[skip] {ticket}: {path} なし")
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = json.dumps(data, ensure_ascii=False)
        client.execute(
            "INSERT INTO analytics_multi_cache (ticket, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (ticket) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
            [ticket, payload, datetime.now().isoformat()],
        )
        print(f"[OK] {ticket}: {len(payload)} バイト")

    # 確認
    r = client.execute("SELECT ticket, length(payload), updated_at FROM analytics_multi_cache")
    print("\n=== Turso保存済み ===")
    for row in r.rows:
        print(f"  {row[0]}: {row[1]} bytes, {row[2]}")

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
