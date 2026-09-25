"""読み取り専用: 2023年データの result/finish_order/payouts 充足率を確認。書き込みなし。"""
import os
import json
from collections import Counter

import libsql_client


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not (url and token):
        print("[NG] TURSO_URL / TURSO_TOKEN 未設定")
        return
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    print("=== 月別 x result/finish/payouts 充足率 ===")
    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    rows = list(r.rows)
    print(f"total rows: {len(rows)}")

    monthly = {}
    for row in rows:
        rid = row[0]
        parts = rid.split("-")
        if len(parts) != 4 or parts[0] != "nar":
            continue
        month = parts[1][:6]
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        rr = p.get("result_runners", [])
        fo = p.get("finish_order", [])
        po = p.get("payouts", {})
        n_runners = len(p.get("runners", []))
        n_result = len(rr) if isinstance(rr, list) else 0
        n_finish = len(fo) if isinstance(fo, list) else 0
        n_payout = len(po) if isinstance(po, dict) else 0
        m = monthly.setdefault(month, {
            "n": 0, "has_result": 0, "has_finish": 0, "has_payout": 0,
            "runner_gt0": 0, "empty_result": 0,
        })
        m["n"] += 1
        if n_result > 0:
            m["has_result"] += 1
        if n_finish > 0:
            m["has_finish"] += 1
        if n_payout > 0:
            m["has_payout"] += 1
        if n_runners > 0:
            m["runner_gt0"] += 1
        if n_runners > 0 and n_result == 0:
            m["empty_result"] += 1

    for month in sorted(monthly):
        m = monthly[month]
        print(f"  {month}: n={m['n']:5d} runners>0={m['runner_gt0']:5d} "
              f"result>0={m['has_result']:5d} finish>0={m['has_finish']:5d} "
              f"payout>0={m['has_payout']:5d} empty_result={m['empty_result']:5d}")

    print("\n=== payout キー別の出現数（2023年全体） ===")
    key_counter = Counter()
    sample_payouts = None
    for row in rows:
        rid = row[0]
        parts = rid.split("-")
        if len(parts) != 4:
            continue
        if not parts[1].startswith("2023"):
            continue
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        po = p.get("payouts", {})
        if isinstance(po, dict):
            for k in po.keys():
                key_counter[k] += 1
            if po and sample_payouts is None:
                sample_payouts = (rid, po)
    for k, c in key_counter.most_common():
        print(f"  {k}: {c}")
    if sample_payouts:
        rid, po = sample_payouts
        print(f"\n  sample [{rid}]:")
        for k, v in po.items():
            s = json.dumps(v, ensure_ascii=False)
            print(f"    {k}: {s[:200]}")
    else:
        print("  2023年の payout サンプルが1件も取れない")

    print("\n=== 出走表の馬番欠落チェック（2023年 先頭50件） ===")
    checked = 0
    bad = 0
    for row in rows:
        rid = row[0]
        parts = rid.split("-")
        if len(parts) != 4 or not parts[1].startswith("2023"):
            continue
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        runners = p.get("runners", [])
        if not runners:
            continue
        nums = sorted([r0.get("horse_number", 0) for r0 in runners])
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            bad += 1
            if bad <= 5:
                print(f"  [{rid}] nums={nums} expected={expected}")
        checked += 1
        if checked >= 50:
            break
    print(f"  checked={checked} bad={bad}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
