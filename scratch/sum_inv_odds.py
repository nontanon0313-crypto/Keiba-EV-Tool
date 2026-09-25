"""Σ(1/odds) から控除率を逆算。オッズ記録の正しさ検証。読み取り専用。"""
import os
import json
from collections import defaultdict
import libsql_client

TICKETS = {
    "quinella": 22.5,
    "wide": 22.5,
    "exacta": 22.5,
    "trio": 25.0,
    "trifecta": 25.0,
    "win": 20.0,
}


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute(
        "SELECT race_id, payload FROM scraped_odds "
        "WHERE race_id LIKE 'nar-2023%' ORDER BY race_id LIMIT 200"
    )
    rows = list(r.rows)
    print(f"対象レース: {len(rows)}\n")

    stats = defaultdict(lambda: {"sum_inv": 0.0, "sum_inv_sq": 0.0,
                                 "n_combos": 0, "n_races": 0,
                                 "sum_implied_rho": 0.0})

    for row in rows:
        rid = row[0]
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        for ticket, expected_rho in TICKETS.items():
            m = p.get(ticket)
            if not isinstance(m, dict) or not m:
                continue
            inv_sum = 0.0
            n = 0
            for combo_key, entry in m.items():
                if not isinstance(entry, dict):
                    continue
                if ticket == "wide":
                    o = entry.get("max") or entry.get("min")
                else:
                    o = entry.get("odds")
                try:
                    o = float(o)
                except (TypeError, ValueError):
                    continue
                if o <= 1.0:
                    continue
                inv_sum += 1.0 / o
                n += 1
            if n == 0 or inv_sum <= 0:
                continue
            implied_rho = (1 - 1.0 / inv_sum) * 100.0
            s = stats[ticket]
            s["sum_inv"] += inv_sum
            s["sum_inv_sq"] += inv_sum * inv_sum
            s["n_combos"] += n
            s["n_races"] += 1
            s["sum_implied_rho"] += implied_rho

    print(f"{'券種':<12} {'レース':>6} {'平均組数':>8} "
          f"{'Σ(1/o)平均':>12} {'理論値':>10} {'逆算ρ%':>10} {'理論ρ%':>10}")
    for ticket, expected_rho in TICKETS.items():
        s = stats[ticket]
        if s["n_races"] == 0:
            print(f"{ticket:<12} {'—':>6}")
            continue
        avg_inv = s["sum_inv"] / s["n_races"]
        avg_combos = s["n_combos"] / s["n_races"]
        implied_rho = s["sum_implied_rho"] / s["n_races"]
        theoretical_inv = 1.0 / (1.0 - expected_rho / 100.0)
        print(f"{ticket:<12} {s['n_races']:>6} {avg_combos:>8.1f} "
              f"{avg_inv:>12.4f} {theoretical_inv:>10.4f} "
              f"{implied_rho:>10.2f} {expected_rho:>10.1f}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
