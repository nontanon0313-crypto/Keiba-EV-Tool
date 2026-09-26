"""馬連の想定利益 vs 実利益の乖離を帯別に確定。
1レースずつDBから読み、メモリを節約。読み取り専用。"""
import os
import time
from datetime import datetime

import libsql_client

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import _candidates
from backend.app.models.schemas import Race, Runner
from backend.scraper.oddspark_keiba import extract_payouts


def race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        runners.append(Runner(
            horse_number=r.get("horse_number", 0),
            frame_number=r.get("frame_number", 0),
            horse_id="", horse_name="", jockey="", trainer="",
            weight=r.get("weight", 55.0) or 55.0,
            odds_win=r.get("odds_win") or 50.0,
            popularity=r.get("popularity"),
        ))
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"):
        surf = "ダート"
    return Race(
        race_id=rid, venue=payload.get("venue", ""), date=payload.get("date", ""),
        race_number=int(payload.get("race_number", 0) or 0),
        start_at=datetime.now(), deadline_at=datetime.now(),
        surface=surf, distance=payload.get("distance") or 1600, runners=runners,
    )


def payout_yen(payouts_dict, ticket_jp, combo):
    m = payouts_dict.get(ticket_jp) or {}
    parts = combo.split("-")
    try:
        combo = "-".join(sorted(parts, key=lambda x: int(x)))
    except ValueError:
        pass
    return m.get(combo)


PROB_BINS = [(0, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.05),
             (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)]
ODDS_BINS = [(1, 10), (10, 30), (30, 100), (100, 300), (300, 1000), (1000, 9999999)]


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    # race_id だけ取得（payload は読まない）
    r = client.execute("SELECT race_id FROM scraped_races ORDER BY race_id")
    rids = [row[0] for row in r.rows][:500]
    print(f"races: {len(rids)} (サンプル500件)", flush=True)

    p_agg = {b: {"n": 0, "sum_prob": 0.0, "hits": 0,
                 "sum_prob_odds": 0.0, "sum_payout_100": 0.0} for b in PROB_BINS}
    o_agg = {b: {"n": 0, "sum_prob": 0.0, "hits": 0,
                 "sum_prob_odds": 0.0, "sum_payout_100": 0.0} for b in ODDS_BINS}

    t0 = time.time()
    processed = 0
    for i, rid in enumerate(rids):
        # 1レース分 payload
        rr = client.execute("SELECT payload FROM scraped_races WHERE race_id=?", [rid])
        rows = list(rr.rows)
        if not rows:
            continue
        import json as _json
        try:
            payload = _json.loads(rows[0][0])
        except Exception:
            continue
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        odds_p = odds_store.get_odds_single(rid)
        if not odds_p:
            continue
        quinella = odds_p.get("quinella") or {}
        if not quinella:
            continue
        payouts_dict = extract_payouts(payload.get("payouts") or {})
        race = race_obj(rid, payload)
        try:
            pred = predict_race(race)
        except Exception:
            continue
        quinella_probs = dict(_candidates(pred, "quinella"))
        w = list(finish[:3])
        sorted_hit = "-".join(str(x) for x in sorted([w[0], w[1]]))
        for combo, prob in quinella_probs.items():
            if prob <= 0:
                continue
            e = quinella.get(combo)
            if not e:
                continue
            o = e.get("odds")
            if not o or o <= 1:
                continue
            o = float(o)
            hit = 1 if combo == sorted_hit else 0
            payout = payout_yen(payouts_dict, "馬連", combo) if hit else 0
            payout_100 = (payout or 0) / 100.0
            for b in PROB_BINS:
                if b[0] <= prob < b[1]:
                    a = p_agg[b]
                    a["n"] += 1
                    a["sum_prob"] += prob
                    a["hits"] += hit
                    a["sum_prob_odds"] += prob * o
                    a["sum_payout_100"] += payout_100
                    break
            for b in ODDS_BINS:
                if b[0] <= o < b[1]:
                    a = o_agg[b]
                    a["n"] += 1
                    a["sum_prob"] += prob
                    a["hits"] += hit
                    a["sum_prob_odds"] += prob * o
                    a["sum_payout_100"] += payout_100
                    break
        processed += 1
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(rids)} processed={processed} {time.time()-t0:.0f}s", flush=True)

    lines = []
    lines.append(f"processed races: {processed}")
    lines.append("")
    lines.append("=== 予想確率帯別（馬連） ===")
    lines.append(f"{'帯':>14} {'N':>8} {'Σ予想':>10} {'実的中':>7} {'実/予想':>8} "
                 f"{'Σ(予想×OD)':>12} {'Σ実払戻/100':>12} {'実/想定':>8}")
    for b in PROB_BINS:
        a = p_agg[b]
        if a["n"] == 0:
            continue
        label = f"{b[0]:.3f}-{b[1]:.3f}"
        ratio_hit = a["hits"] / a["sum_prob"] if a["sum_prob"] > 0 else 0
        ratio_pay = a["sum_payout_100"] / a["sum_prob_odds"] if a["sum_prob_odds"] > 0 else 0
        lines.append(f"{label:>14} {a['n']:>8} {a['sum_prob']:>10.1f} {a['hits']:>7} "
                     f"{ratio_hit:>8.3f} {a['sum_prob_odds']:>12.1f} {a['sum_payout_100']:>12.1f} "
                     f"{ratio_pay:>8.3f}")
    lines.append("")
    lines.append("=== オッズ帯別（馬連） ===")
    lines.append(f"{'帯':>14} {'N':>8} {'Σ予想':>10} {'実的中':>7} {'実/予想':>8} "
                 f"{'Σ(予想×OD)':>12} {'Σ実払戻/100':>12} {'実/想定':>8}")
    for b in ODDS_BINS:
        a = o_agg[b]
        if a["n"] == 0:
            continue
        label = f"{b[0]}-{b[1]}" if b[1] < 9999999 else f"{b[0]}+"
        ratio_hit = a["hits"] / a["sum_prob"] if a["sum_prob"] > 0 else 0
        ratio_pay = a["sum_payout_100"] / a["sum_prob_odds"] if a["sum_prob_odds"] > 0 else 0
        lines.append(f"{label:>14} {a['n']:>8} {a['sum_prob']:>10.1f} {a['hits']:>7} "
                     f"{ratio_hit:>8.3f} {a['sum_prob_odds']:>12.1f} {a['sum_payout_100']:>12.1f} "
                     f"{ratio_pay:>8.3f}")
    out = "\n".join(lines)
    print(out, flush=True)
    with open("analyze_quinella_result.txt", "w", encoding="utf-8") as f:
        f.write(out)

    try:
        client.close()
    except Exception:
        pass


try:
    main()
except BaseException as e:
    import traceback
    with open("analyze_quinella_err.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print(f"ERROR: {e}", flush=True)
import os as _o
_o._exit(0)
