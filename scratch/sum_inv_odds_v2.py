"""Σ(1/odds) から控除率を逆算。9999.9は除外して検証。読み取り専用。"""
import os
import json
from collections import defaultdict
import libsql_client

# 券種: (控除率%, 的中点数)
TICKETS = {
    "quinella": (22.5, 1),
    "wide":     (22.5, 3),
    "exacta":   (22.5, 1),
    "trio":     (25.0, 1),
    "trifecta": (25.0, 1),
}

ODDS_DISPLAY_MAX = 9999.9


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute(
        "SELECT race_id, payload FROM scraped_odds ORDER BY race_id"
    )
    rows = list(r.rows)
    print(f"対象レース: {len(rows)}\n")

    stats = defaultdict(lambda: {"sum_inv": 0.0, "n_combos": 0,
                                 "n_races": 0, "n_9999": 0,
                                 "sum_implied_rho": 0.0})

    for row in rows:
        rid = row[0]
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        for ticket, (rho, hits) in TICKETS.items():
            m = p.get(ticket)
            if not isinstance(m, dict) or not m:
                continue
            inv_sum = 0.0
            n = 0
            n9999 = 0
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
                if o >= ODDS_DISPLAY_MAX:
                    n9999 += 1
                    continue
                if o <= 1.0:
                    continue
                inv_sum += 1.0 / o
                n += 1
            if n == 0 or inv_sum <= 0:
                continue
            # 理論値: 的中点数 / (1-ρ)
            theoretical = hits / (1.0 - rho / 100.0)
            implied_rho = (1 - hits / inv_sum) * 100.0 if inv_sum > 0 else 0.0
            s = stats[ticket]
            s["sum_inv"] += inv_sum
            s["n_combos"] += n
            s["n_races"] += 1
            s["n_9999"] += n9999
            s["sum_implied_rho"] += implied_rho

    print(f"{'券種':<10} {'レース':>6} {'平均組':>8} {'平均9999':>9} "
          f"{'Σ(1/o)平均':>12} {'理論値':>10} {'逆算ρ%':>10} {'理論ρ%':>8}")
    for ticket, (rho, hits) in TICKETS.items():
        s = stats[ticket]
        if s["n_races"] == 0:
            print(f"{ticket:<10} データなし")
            continue
        avg_inv = s["sum_inv"] / s["n_races"]
        avg_combos = s["n_combos"] / s["n_races"]
        avg_9999 = s["n_9999"] / s["n_races"]
        theoretical = hits / (1.0 - rho / 100.0)
        implied = s["sum_implied_rho"] / s["n_races"]
        print(f"{ticket:<10} {s['n_races']:>6} {avg_combos:>8.1f} {avg_9999:>9.1f} "
              f"{avg_inv:>12.4f} {theoretical:>10.4f} "
              f"{implied:>10.2f} {rho:>8.1f}")

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
