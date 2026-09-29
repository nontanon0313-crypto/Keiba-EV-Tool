"""枠番 × 会場 × 芝/ダート × 距離帯 × 馬場状態 の集計。

単勝を対象。各セルで枠番ごとに n, 実利益%, 95%CI, 的中率, 95%CI を計算。
Turso の新テーブル analytics_frame_cache に保存。
"""
import os
import json
import math
import time
from collections import defaultdict
from datetime import datetime

import libsql_client

from backend.constants import (
    DISTANCE_BINS, TRACK_CD_TO_VENUE, EXCLUDED_TRACK_CODES, ODDS_MISSING_LEGACY,
    STAKE_PER_BET,
)


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    rows = list(r.rows)
    print(f"全レース: {len(rows)}", flush=True)

    # (venue, surface, dist_label, baba) → frame → 累積値
    cells = defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "hits": 0,
        "sum_profit": 0.0, "sum_profit_sq": 0.0,
        "sum_market_prob": 0.0, "sum_rho": 0.0,
        "sum_payout": 0.0,
    }))

    t0 = time.time()
    n_used = 0
    n_skipped = 0

    for idx, row in enumerate(rows):
        rid = row[0]
        parts = rid.split("-")
        if len(parts) >= 3 and parts[2] in EXCLUDED_TRACK_CODES:
            n_skipped += 1
            continue
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        runners = p.get("runners", [])
        finish_order = p.get("finish_order") or []
        payouts = p.get("payouts") or {}
        if not runners or not finish_order:
            continue
        win_payouts = {}
        for prow in (payouts.get("単勝") or []):
            if isinstance(prow, list) and len(prow) >= 3:
                try:
                    num = int(prow[1])
                    amt = int(prow[2].replace(",", "").replace("円", ""))
                    win_payouts[num] = amt
                except Exception:
                    pass
        baba = p.get("track_condition")
        if not baba or baba == "不明":
            n_skipped += 1
            continue
        surface = p.get("surface", "不明")
        if surface not in ("芝", "ダート", "障害"):
            continue
        venue = TRACK_CD_TO_VENUE.get(parts[2] if len(parts) >= 3 else "", None)
        if not venue:
            continue
        distance = p.get("distance") or 0
        dist_label = None
        for lo, hi in DISTANCE_BINS:
            if lo <= distance < hi:
                dist_label = f"{lo}-{hi}"
                break
        if dist_label is None:
            continue
        # 単勝の Σ(1/odds) → レース排除率
        inv_sum = 0.0
        for r0 in runners:
            o = r0.get("odds_win")
            if o and o > 1 and o != ODDS_MISSING_LEGACY:
                inv_sum += 1.0 / float(o)
        if inv_sum <= 0:
            n_skipped += 1
            continue
        rho_race = 1.0 - 1.0 / inv_sum
        market_factor = 1.0 - rho_race

        winner = finish_order[0]
        cell_key = (venue, surface, dist_label, baba)
        for r0 in runners:
            num = r0.get("horse_number")
            frame = r0.get("frame_number")
            odds = r0.get("odds_win")
            if num is None or frame is None or odds is None:
                continue
            if odds == ODDS_MISSING_LEGACY or odds == 1.0:
                continue
            market_prob = market_factor / float(odds)
            is_hit = 1 if num == winner else 0
            payout = win_payouts.get(num, 0) if is_hit else 0
            profit = payout / float(STAKE_PER_BET) - 1.0
            acc = cells[cell_key][int(frame)]
            acc["n"] += 1
            acc["hits"] += is_hit
            acc["sum_profit"] += profit
            acc["sum_profit_sq"] += profit * profit
            acc["sum_payout"] += payout
            acc["sum_market_prob"] += market_prob
            acc["sum_rho"] += rho_race
        n_used += 1
        if (idx + 1) % 500 == 0:
            print(f"  {idx+1}/{len(rows)} {time.time()-t0:.0f}s", flush=True)

    print(f"\n=== 集計完了: {n_used} レース使用, {n_skipped} スキップ ===", flush=True)
    print(f"セル数: {len(cells)}", flush=True)

    z = 1.96
    out_cells = []
    for cell_key, frames_data in cells.items():
        venue, surface, dist_label, baba = cell_key
        total_n = sum(fd["n"] for fd in frames_data.values())
        if total_n < 1:
            continue
        frames_out = []
        for f in range(1, 9):
            fd = frames_data.get(f)
            if not fd or fd["n"] == 0:
                frames_out.append({
                    "frame": f, "n": 0,
                    "roi_pct": None, "roi_ci_lo": None, "roi_ci_hi": None,
                    "hr_pct": None, "hr_ci_lo": None, "hr_ci_hi": None,
                })
                continue
            n = fd["n"]
            mean_profit = fd["sum_profit"] / n
            var_profit = fd["sum_profit_sq"] / n - mean_profit * mean_profit
            var_profit = max(var_profit, 0.0)
            se_profit = math.sqrt(var_profit / n) if n > 0 else 0.0
            roi_pct = mean_profit * 100
            roi_ci_lo = (mean_profit - z * se_profit) * 100
            roi_ci_hi = (mean_profit + z * se_profit) * 100
            p_hat = fd["hits"] / n
            se_p = math.sqrt(p_hat * (1 - p_hat) / n) if n > 0 else 0.0
            frames_out.append({
                "frame": f, "n": n,
                "sum_profit": fd["sum_profit"],
                "sum_profit_sq": fd["sum_profit_sq"],
                "sum_hit": fd["hits"],
                "sum_payout": fd["sum_payout"],
                "sum_market_prob": fd["sum_market_prob"],
                "sum_rho": fd["sum_rho"],
                "roi_pct": roi_pct,
                "roi_ci_lo": roi_ci_lo,
                "roi_ci_hi": roi_ci_hi,
                "hr_pct": p_hat * 100,
                "hr_ci_lo": (p_hat - z * se_p) * 100,
                "hr_ci_hi": (p_hat + z * se_p) * 100,
            })
        out_cells.append({
            "venue": venue,
            "surface": surface,
            "distance_band": dist_label,
            "track_condition": baba,
            "total_n": total_n,
            "frames": frames_out,
        })

    print(f"出力セル数: {len(out_cells)}", flush=True)

    result = {
        "cells": out_cells,
        "n_races": n_used,
        "generated_at": datetime.now().isoformat(),
    }

    client.execute(
        "CREATE TABLE IF NOT EXISTS analytics_frame_cache ("
        "id INTEGER PRIMARY KEY,"
        "payload TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    payload_str = json.dumps(result, ensure_ascii=False)
    client.execute(
        "INSERT INTO analytics_frame_cache (id, payload, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
        [payload_str, datetime.now().isoformat()],
    )
    print(f"saved turso ({len(payload_str)} bytes)", flush=True)

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
