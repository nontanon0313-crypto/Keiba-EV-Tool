"""23レース分のデータ品質を確認。読み取り専用。"""
import os
import json
from collections import Counter
import libsql_client

EXPECTED_TICKETS = ["単勝", "複勝", "枠連", "枠単", "馬連", "馬単", "ワイド", "3連複", "3連単"]
EXPECTED_ODDS = ["quinella", "wide", "exacta", "trio", "trifecta"]

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
client = libsql_client.create_client_sync(url=http_url, auth_token=token)

print("=== 1) scraped_races ===")
r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
races = list(r.rows)
print(f"件数: {len(races)}")

print("\n=== 2) 各レースのデータ充足 ===")
problems = []
for row in races:
    rid = row[0]
    try:
        p = json.loads(row[1])
    except Exception as e:
        problems.append((rid, f"payload parse error: {e}"))
        continue
    n_runners = len(p.get("runners", []))
    n_result = len(p.get("result_runners", []))
    n_finish = len(p.get("finish_order", []))
    payouts = p.get("payouts", {}) or {}
    # 券種の網羅（発売なしは欠ける場合あり）
    missing = [t for t in EXPECTED_TICKETS if t not in payouts]
    # 想定外キー（数字や組み合わせキー）
    extra = [k for k in payouts.keys() if k not in EXPECTED_TICKETS]
    nums = sorted([r0.get("horse_number", 0) for r0 in p.get("runners", [])])
    expected_nums = list(range(1, len(nums) + 1)) if nums else []
    issue = []
    if n_runners == 0: issue.append("runners空")
    if nums != expected_nums: issue.append(f"馬番欠落 {nums}")
    if n_result == 0: issue.append("result空")
    if n_finish < 3: issue.append(f"finish<3 ({n_finish})")
    if missing: issue.append(f"券種欠け {missing}")
    if extra: issue.append(f"想定外キー {extra[:3]}")
    if issue:
        problems.append((rid, " / ".join(issue)))
    else:
        print(f"  {rid}: OK (n_runners={n_runners}, 券種={len(payouts)})")

if problems:
    print(f"\n=== 問題 {len(problems)} 件 ===")
    for rid, msg in problems[:30]:
        print(f"  {rid}: {msg}")

print("\n=== 3) scraped_odds ===")
r2 = client.execute("SELECT race_id, payload FROM scraped_odds ORDER BY race_id")
odds_rows = list(r2.rows)
print(f"件数: {len(odds_rows)}")
bad_odds = 0
n_with_9999 = 0
for row in odds_rows:
    rid = row[0]
    try:
        p = json.loads(row[1])
    except Exception:
        bad_odds += 1
        continue
    has_9999 = False
    for tk in EXPECTED_ODDS:
        m = p.get(tk)
        if not isinstance(m, dict):
            continue
        for k, v in m.items():
            if isinstance(v, dict):
                if v.get("odds") == 9999.9 or v.get("max") == 9999.9:
                    has_9999 = True
                    break
        if has_9999: break
    if has_9999:
        n_with_9999 += 1
print(f"parse error: {bad_odds}")
print(f"9999.9 を含むレース: {n_with_9999} / {len(odds_rows)}")

print("\n=== 4) サンプル1件の詳細 ===")
if odds_rows:
    p = json.loads(odds_rows[0][1])
    print(f"  rid: {odds_rows[0][0]}")
    for tk in EXPECTED_ODDS:
        m = p.get(tk) or {}
        n = len(m)
        n9999 = sum(1 for v in m.values() if isinstance(v, dict) and (v.get("odds") == 9999.9 or v.get("max") == 9999.9))
        print(f"    {tk}: {n}組 (9999.9={n9999})")

try:
    client.close()
except Exception:
    pass
import os as _o
_o._exit(0)
