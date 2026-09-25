"""読み取り専用: Turso内のレース/オッズ分布とサンプル構造を確認。書き込みなし。"""
import os
import json
from collections import Counter

import libsql_client


def trunc(v, n=200):
    s = str(v)
    return s if len(s) <= n else s[:n] + "..."


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not (url and token):
        print("[NG] TURSO_URL / TURSO_TOKEN が未設定")
        return
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    print("=== 1) テーブル件数 ===")
    for tbl in ("scraped_races", "scraped_odds"):
        try:
            r = client.execute(f"SELECT COUNT(*) FROM {tbl}")
            print(f"  {tbl}: {r.rows[0][0]}")
        except Exception as e:
            print(f"  {tbl}: ERROR {e}")

    print("\n=== 2) race_id の分布 ===")
    r = client.execute("SELECT race_id FROM scraped_races")
    race_ids = [row[0] for row in r.rows]
    print(f"  total: {len(race_ids)}")
    dates = []
    venues = Counter()
    bad = []
    for rid in race_ids:
        parts = rid.split("-")
        if len(parts) != 4 or parts[0] != "nar":
            bad.append(rid)
            continue
        _, d, track, rn = parts
        dates.append(d)
        venues[track] += 1
    if bad:
        print(f"  unparseable: {len(bad)} sample={bad[:3]}")
    if dates:
        dates_sorted = sorted(dates)
        print(f"  date range: {dates_sorted[0]} 〜 {dates_sorted[-1]}")
        print(f"  unique days: {len(set(dates))}")
        print("  月別件数:")
        months = Counter(d[:6] for d in dates)
        for m in sorted(months):
            print(f"    {m}: {months[m]}")
    print("  会場(track_cd)別:")
    for t, c in sorted(venues.items()):
        print(f"    {t}: {c}")

    print("\n=== 3) オッズ側 race_id の突合 ===")
    r = client.execute("SELECT race_id FROM scraped_odds")
    odds_ids = set(row[0] for row in r.rows)
    race_id_set = set(race_ids)
    only_race = race_id_set - odds_ids
    only_odds = odds_ids - race_id_set
    both = race_id_set & odds_ids
    print(f"  race_only: {len(only_race)}")
    print(f"  odds_only: {len(only_odds)}")
    print(f"  both:      {len(both)}")

    print("\n=== 4) race payload サンプル (最新3件) ===")
    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id DESC LIMIT 3")
    for row in r.rows:
        rid = row[0]
        try:
            p = json.loads(row[1])
        except Exception as e:
            print(f"  [{rid}] payload parse error: {e}")
            continue
        print(f"\n  [{rid}]")
        print(f"    keys: {list(p.keys())}")
        print(f"    venue={p.get('venue')} date={p.get('date')} R={p.get('race_number')} "
              f"surface={p.get('surface')} distance={p.get('distance')}")
        runners = p.get("runners", [])
        print(f"    runners: {len(runners)}")
        if runners:
            nums = [r0.get("horse_number") for r0 in runners]
            names = [r0.get("horse_name") for r0 in runners]
            print(f"      horse_numbers: {nums}")
            print(f"      horse_names(first3): {names[:3]}")
            print(f"      sample[0]: {trunc(runners[0])}")
        rr = p.get("result_runners", [])
        print(f"    result_runners: {len(rr)}")
        if rr:
            print(f"      sample[0]: {trunc(rr[0])}")
        fo = p.get("finish_order", [])
        print(f"    finish_order: {fo}")
        payouts = p.get("payouts", {})
        if isinstance(payouts, dict):
            print(f"    payouts keys: {list(payouts.keys())}")
            for k, v in payouts.items():
                print(f"      {k}: {trunc(v, 160)}")
        else:
            print(f"    payouts: {trunc(payouts)}")

    print("\n=== 5) odds payload サンプル (最新3件) ===")
    r = client.execute("SELECT race_id, payload FROM scraped_odds ORDER BY race_id DESC LIMIT 3")
    for row in r.rows:
        rid = row[0]
        try:
            p = json.loads(row[1])
        except Exception as e:
            print(f"  [{rid}] payload parse error: {e}")
            continue
        print(f"\n  [{rid}]")
        if isinstance(p, dict):
            for k, v in p.items():
                if isinstance(v, dict):
                    ks = list(v.keys())[:5]
                    print(f"    {k}: dict n={len(v)} keys(sample)={ks}")
                    for kk in list(v.keys())[:1]:
                        print(f"      {kk}: {trunc(v[kk], 160)}")
                elif isinstance(v, list):
                    print(f"    {k}: list n={len(v)} sample={trunc(v[:2], 160)}")
                else:
                    print(f"    {k}: {type(v).__name__} = {trunc(v, 120)}")
        else:
            print(f"    type: {type(p)} value={trunc(p)}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
