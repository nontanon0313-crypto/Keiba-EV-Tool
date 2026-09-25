"""DB の payouts 構造を20件で確認。読み取り専用。"""
import os
import re
import json
from collections import Counter
import libsql_client


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute(
        "SELECT race_id, payload FROM scraped_races "
        "WHERE race_id LIKE 'nar-2023%' ORDER BY race_id LIMIT 200"
    )
    rows = list(r.rows)

    samples = []
    for row in rows:
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        if p.get("payouts"):
            samples.append((row[0], p))
        if len(samples) >= 20:
            break

    print(f"対象: {len(samples)}件\n")

    # 全券種キーの出現
    key_counter = Counter()
    # 期待する券種名
    EXPECTED = ["単勝", "複勝", "枠連", "枠単", "馬連", "馬単", "ワイド", "3連複", "3連単"]
    expected_ok = Counter()
    # 券種ごとの行数分布
    ticket_rowcounts = {}

    for rid, p in samples:
        po = p.get("payouts", {})
        for k in po.keys():
            key_counter[k] += 1
        for k in EXPECTED:
            if k in po:
                expected_ok[k] += 1
        for k, v in po.items():
            n = len(v) if isinstance(v, list) else 0
            ticket_rowcounts.setdefault(k, []).append(n)

    print("=== キー別出現数 ===")
    for k, c in sorted(key_counter.items(), key=lambda x: -x[1]):
        print(f"  {k}: {c}")

    print("\n=== 期待券種の出現数 ===")
    for k in EXPECTED:
        print(f"  {k}: {expected_ok[k]}/{len(samples)}")

    print("\n=== 券種ごとの行数分布（サンプル） ===")
    for k in EXPECTED:
        vals = ticket_rowcounts.get(k, [])
        if vals:
            from collections import Counter as C
            dist = C(vals)
            print(f"  {k}: 行数分布={dict(dist)}")

    print("\n=== サンプル3件の中身 ===")
    for rid, p in samples[:3]:
        print(f"\n[{rid}]")
        po = p.get("payouts", {})
        for k, v in po.items():
            s = json.dumps(v, ensure_ascii=False)
            print(f"  {k}: {s[:250]}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
