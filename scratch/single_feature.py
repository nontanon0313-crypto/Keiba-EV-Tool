"""単勝・各特徴を単独で検証。
各ビン B を B^c (補集合) と比較。Bonferroni補正。
ROI と 的中率 の両方を検定。読み取り専用。
"""
import os
import json
import math
import re as _re
import time
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
import libsql_client
from scipy import stats


def build_dataset():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    venue_ids = {}
    r = client.execute("SELECT DISTINCT race_id FROM scraped_races")
    for row in r.rows:
        parts = row[0].split("-")
        if len(parts) >= 3:
            venue_ids[parts[2]] = len(venue_ids)

    r = client.execute("SELECT payload FROM scraped_races LIMIT 1000")
    jockey_counter = Counter()
    for row in r.rows:
        try:
            p = json.loads(row[0])
        except Exception:
            continue
        for rr in p.get("result_runners", []):
            j = (rr.get("jockey") or "").strip()
            if j:
                jockey_counter[j] += 1
    top_jockeys = [j for j, _ in jockey_counter.most_common(20)]
    jockey_ids = {j: i for i, j in enumerate(top_jockeys)}

    records = []
    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    rows = list(r.rows)
    print(f"races: {len(rows)}", flush=True)
    t0 = time.time()
    for i, row in enumerate(rows):
        rid = row[0]
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        runners = p.get("runners", [])
        result_runners = p.get("result_runners", [])
        finish_order = p.get("finish_order") or []
        payouts = p.get("payouts") or {}
        if len(finish_order) < 1 or not runners:
            continue
        n_runners = len(runners)
        distance = p.get("distance") or 0
        surf = p.get("surface") or "ダート"
        surf_id = {"ダート": 0, "芝": 1, "障害": 2}.get(surf, 0)
        parts = rid.split("-")
        venue_id = venue_ids.get(parts[2], -1)

        win_payouts = {}
        for row2 in (payouts.get("単勝") or []):
            if isinstance(row2, list) and len(row2) >= 3:
                try:
                    combo = int(row2[1])
                    amt = int(row2[2].replace(",", "").replace("円", ""))
                    win_payouts[combo] = amt
                except Exception:
                    pass

        rr_map = {}
        for rr in result_runners:
            n = rr.get("horse_number")
            if n is not None:
                rr_map[n] = rr

        for r0 in runners:
            num = r0.get("horse_number")
            odds = r0.get("odds_win")
            pop = r0.get("popularity")
            frame = r0.get("frame_number")
            if num is None or odds is None:
                continue
            rr = rr_map.get(num)
            weight = rr.get("weight") if rr else None
            if weight is None:
                weight = r0.get("weight")
            hw_chg = rr.get("horse_weight_change") if rr else None
            hw = rr.get("horse_weight") if rr else None
            if hw is None:
                hw = r0.get("horse_weight")
            sex_id = -1
            age = 0.0
            jockey_id = len(jockey_ids)
            if rr:
                age_sex = rr.get("age_sex") or ""
                if age_sex:
                    if age_sex[0] == "牡": sex_id = 0
                    elif age_sex[0] == "牝": sex_id = 1
                    elif age_sex[0] == "セ": sex_id = 2
                    m = _re.search(r"(\d+)", age_sex)
                    if m:
                        age = float(m.group(1))
                j = (rr.get("jockey") or "").strip()
                if j in jockey_ids:
                    jockey_id = jockey_ids[j]
            payout = win_payouts.get(num, 0) if num == finish_order[0] else 0
            records.append({
                "odds": float(odds),
                "pop": float(pop) if pop is not None else 0.0,
                "frame": float(frame or 0),
                "weight": float(weight) if weight is not None else -1.0,
                "has_weight": 1 if weight is not None else 0,
                "sex_id": float(sex_id),
                "age": float(age),
                "hw": float(hw) if hw is not None else -1.0,
                "has_hw": 1 if hw is not None else 0,
                "hw_chg": float(hw_chg) if hw_chg is not None else -999.0,
                "has_hw_chg": 1 if hw_chg is not None else 0,
                "n_runners": float(n_runners),
                "distance": float(distance),
                "surface_id": float(surf_id),
                "venue_id": float(venue_id),
                "jockey_id": float(jockey_id),
                "jockey_rank": -1,
                "payout": float(payout),
            })
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(rows)} {time.time()-t0:.0f}s N={len(records)}", flush=True)

    try:
        client.close()
    except Exception:
        pass
    return records


def main():
    print("=== build_dataset ===", flush=True)
    records = build_dataset()
    N = len(records)
    print(f"N: {N}", flush=True)

    # 騎手勝率ランク
    jk_total = defaultdict(int)
    jk_win = defaultdict(int)
    for r in records:
        jid = int(r["jockey_id"])
        jk_total[jid] += 1
        if r["payout"] > 0:
            jk_win[jid] += 1
    valid_jk = [(jid, jk_win[jid] / jk_total[jid]) for jid in jk_total if jk_total[jid] >= 20]
    valid_jk.sort(key=lambda x: x[1], reverse=True)
    top_n = max(1, len(valid_jk) // 3)
    top_set = set(j for j, _ in valid_jk[:top_n])
    mid_set = set(j for j, _ in valid_jk[top_n:2*top_n])
    bot_set = set(j for j, _ in valid_jk[2*top_n:])
    for r in records:
        jid = int(r["jockey_id"])
        if jid in top_set:
            r["jockey_rank"] = 0
        elif jid in mid_set:
            r["jockey_rank"] = 1
        elif jid in bot_set:
            r["jockey_rank"] = 2
    print(f"jockey_rank: top={len(top_set)} mid={len(mid_set)} bot={len(bot_set)}", flush=True)

    has_w = sum(1 for r in records if r["has_weight"])
    has_hc = sum(1 for r in records if r["has_hw_chg"])
    print(f"weight 取得: {has_w}/{N}", flush=True)
    print(f"hw_chg 取得: {has_hc}/{N}", flush=True)

    def make_bins():
        bins = []
        for lo, hi in [(3,4),(4,5),(5,6),(6,7),(7,8),(8,20)]:
            bins.append(("age", f"{lo}-{hi-1}歳", lambda r, lo=lo, hi=hi: lo <= r["age"] < hi))
        for lo, hi in [(0,53),(53,54),(54,55),(55,56),(56,57),(57,58),(58,100)]:
            bins.append(("weight", f"斤量 {lo}-{hi}", lambda r, lo=lo, hi=hi: r["has_weight"] and lo <= r["weight"] < hi))
        for lo, hi in [(-100,-10),(-10,-5),(-5,0),(0,1),(1,5),(5,10),(10,100)]:
            bins.append(("hw_chg", f"体重増減 {lo}~{hi}", lambda r, lo=lo, hi=hi: r["has_hw_chg"] and lo <= r["hw_chg"] < hi))
        for f in range(1, 9):
            bins.append(("frame", f"枠 {f}", lambda r, f=f: r["frame"] == f))
        for sid, name in [(0,"牡"),(1,"牝"),(2,"セ"),(-1,"不明")]:
            bins.append(("sex_id", f"性別 {name}", lambda r, sid=sid: r["sex_id"] == sid))
        for nr in range(6, 17):
            bins.append(("n_runners", f"頭数 {nr}", lambda r, nr=nr: int(r["n_runners"]) == nr))
        for lo, hi in [(0,1000),(1000,1200),(1200,1400),(1400,1600),(1600,1800),(1800,2000),(2000,3000)]:
            bins.append(("distance", f"距離 {lo}-{hi}", lambda r, lo=lo, hi=hi: lo <= r["distance"] < hi))
        for sid, name in [(0,"ダート"),(1,"芝"),(2,"障害")]:
            bins.append(("surface_id", f"馬場 {name}", lambda r, sid=sid: r["surface_id"] == sid))
        venue_set = set(int(r["venue_id"]) for r in records)
        for vid in sorted(venue_set):
            bins.append(("venue_id", f"会場 {vid}", lambda r, vid=vid: int(r["venue_id"]) == vid))
        jk_set = set(int(r["jockey_id"]) for r in records)
        for jid in sorted(jk_set):
            bins.append(("jockey_id", f"騎手ID {jid}", lambda r, jid=jid: int(r["jockey_id"]) == jid))
        for lo, hi, name in [(1,2,"1番人気"),(2,3,"2番人気"),(3,4,"3番人気"),
                             (4,7,"4-6番人気"),(7,10,"7-9番人気"),(10,100,"10番人気+")]:
            bins.append(("pop", name, lambda r, lo=lo, hi=hi: lo <= r["pop"] < hi))
        for lo, hi, name in [(1,3,"オッズ1-3"),(3,5,"オッズ3-5"),(5,10,"オッズ5-10"),
                             (10,20,"オッズ10-20"),(20,50,"オッズ20-50"),
                             (50,100,"オッズ50-100"),(100,99999,"オッズ100+")]:
            bins.append(("odds", name, lambda r, lo=lo, hi=hi: lo <= r["odds"] < hi))
        for rank, name in [(0,"騎手 上位"),(1,"騎手 中位"),(2,"騎手 下位")]:
            bins.append(("jockey_rank", name, lambda r, rank=rank: r["jockey_rank"] == rank))
        return bins

    all_bins = make_bins()
    K = len(all_bins)
    alpha = 0.05
    z_adj = stats.norm.ppf(1 - alpha / (2 * K))
    print(f"\n総検定数 K = {K}, Bonferroni z_adj = {z_adj:.4f}", flush=True)

    profits = np.array([r["payout"] / 100.0 - 1.0 for r in records])
    hits = (np.array([r["payout"] for r in records]) > 0).astype(np.float64)
    odds_arr = np.array([r["odds"] for r in records])
    payouts_arr = np.array([r["payout"] for r in records])

    results = []
    for feature, label, pred in all_bins:
        mask = np.array([pred(r) for r in records], dtype=bool)
        n_B = int(mask.sum())
        n_C = N - n_B
        if n_B < 100 or n_C < 100:
            continue
        pB = profits[mask]
        pC = profits[~mask]
        mean_B = float(pB.mean()); mean_C = float(pC.mean())
        se_B = float(pB.std(ddof=1) / math.sqrt(n_B))
        se_C = float(pC.std(ddof=1) / math.sqrt(n_C))
        diff = mean_B - mean_C
        se_diff = math.sqrt(se_B**2 + se_C**2)
        roi_ci_lo = diff - z_adj * se_diff
        roi_ci_hi = diff + z_adj * se_diff

        # 的中率
        h_B = hits[mask]
        h_C = hits[~mask]
        hr_B = float(h_B.mean())
        hr_C = float(h_C.mean())
        se_h_B = math.sqrt(hr_B * (1 - hr_B) / n_B) if n_B > 0 else 0.0
        se_h_C = math.sqrt(hr_C * (1 - hr_C) / n_C) if n_C > 0 else 0.0
        hr_diff = hr_B - hr_C
        se_hr_diff = math.sqrt(se_h_B**2 + se_h_C**2)
        hr_ci_lo = hr_diff - z_adj * se_hr_diff
        hr_ci_hi = hr_diff + z_adj * se_hr_diff

        # 平均オッズ・平均払戻
        avg_odds_B = float(odds_arr[mask].mean())
        avg_odds_C = float(odds_arr[~mask].mean())
        if h_B.sum() > 0:
            avg_payout_B = float(payouts_arr[mask][h_B > 0].mean())
        else:
            avg_payout_B = 0.0
        if h_C.sum() > 0:
            avg_payout_C = float(payouts_arr[~mask][h_C > 0].mean())
        else:
            avg_payout_C = 0.0

        results.append({
            "feature": feature,
            "label": label,
            "n": n_B,
            "n_other": n_C,
            "roi": float(pB.sum() / n_B) + 1.0,
            "roi_other": float(pC.sum() / n_C) + 1.0,
            "roi_diff": diff,
            "roi_ci_lo": float(roi_ci_lo),
            "roi_ci_hi": float(roi_ci_hi),
            "roi_sig_up": roi_ci_lo > 0,
            "roi_sig_down": roi_ci_hi < 0,
            "hit_rate": hr_B,
            "hit_rate_other": hr_C,
            "hr_diff": hr_diff,
            "hr_ci_lo": float(hr_ci_lo),
            "hr_ci_hi": float(hr_ci_hi),
            "hr_sig_up": hr_ci_lo > 0,
            "hr_sig_down": hr_ci_hi < 0,
            "avg_odds": avg_odds_B,
            "avg_odds_other": avg_odds_C,
            "avg_payout_hit": avg_payout_B,
            "avg_payout_hit_other": avg_payout_C,
        })

    print(f"\n=== 有効ビン数: {len(results)} ===\n")

    print(f"--- ROI 有意優位 (B > B^c) ---")
    sig_roi_up = [r for r in results if r["roi_sig_up"]]
    for r in sorted(sig_roi_up, key=lambda x: -x["roi_diff"]):
        print(f"  [{r['feature']:>10}] {r['label']:>18} n={r['n']:>6} "
              f"ROI={r['roi']:.4f}/{r['roi_other']:.4f} "
              f"diff={r['roi_diff']:+.4f} CI=[{r['roi_ci_lo']:+.4f},{r['roi_ci_hi']:+.4f}]")
    if not sig_roi_up:
        print("  なし")

    print(f"\n--- ROI 有意劣位 (B < B^c) ---")
    sig_roi_dn = [r for r in results if r["roi_sig_down"]]
    for r in sorted(sig_roi_dn, key=lambda x: x["roi_diff"]):
        print(f"  [{r['feature']:>10}] {r['label']:>18} n={r['n']:>6} "
              f"ROI={r['roi']:.4f}/{r['roi_other']:.4f} "
              f"diff={r['roi_diff']:+.4f} CI=[{r['roi_ci_lo']:+.4f},{r['roi_ci_hi']:+.4f}]")
    if not sig_roi_dn:
        print("  なし")

    print(f"\n--- 的中率 有意優位 (B > B^c) ---")
    sig_hr_up = [r for r in results if r["hr_sig_up"]]
    for r in sorted(sig_hr_up, key=lambda x: -x["hr_diff"]):
        print(f"  [{r['feature']:>10}] {r['label']:>18} n={r['n']:>6} "
              f"的中率={r['hit_rate']*100:.2f}%/{r['hit_rate_other']*100:.2f}% "
              f"オッズ={r['avg_odds']:.1f}/{r['avg_odds_other']:.1f} "
              f"払戻(的中時)={r['avg_payout_hit']:.0f}/{r['avg_payout_hit_other']:.0f}")
    if not sig_hr_up:
        print("  なし")

    print(f"\n--- 的中率 有意劣位 (B < B^c) ---")
    sig_hr_dn = [r for r in results if r["hr_sig_down"]]
    for r in sorted(sig_hr_dn, key=lambda x: x["hr_diff"]):
        print(f"  [{r['feature']:>10}] {r['label']:>18} n={r['n']:>6} "
              f"的中率={r['hit_rate']*100:.2f}%/{r['hit_rate_other']*100:.2f}% "
              f"オッズ={r['avg_odds']:.1f}/{r['avg_odds_other']:.1f}")
    if not sig_hr_dn:
        print("  なし")

    # === features 構造に再編成 ===
    # 出走表タブ: pop, weight, frame, odds, sex_id
    # 単独特徴タブ: age, hw_chg, n_runners, distance, surface_id, venue_id, jockey_id, jockey_rank
    RACE_TABLE_FEATURES = [
        ("pop", "人気"),
        ("weight", "斤量"),
        ("frame", "枠番"),
        ("odds", "単勝オッズ"),
        ("sex_id", "性別"),
    ]
    SINGLE_FEATURES = [
        ("age", "年齢"),
        ("hw_chg", "馬体重増減"),
        ("n_runners", "頭数"),
        ("distance", "距離"),
        ("surface_id", "馬場"),
        ("venue_id", "会場"),
        ("jockey_id", "騎手"),
        ("jockey_rank", "騎手ランク"),
    ]

    def to_pct(v):
        try:
            return float(v) * 100
        except Exception:
            return v

    def build_feature_rows(feature_key):
        rs = [r for r in results if r["feature"] == feature_key]
        rows = []
        for r in rs:
            rows.append({
                "label": r["label"],
                "n": r["n"],
                "n_other": r["n_other"],
                "roi_pct": to_pct(r["roi"]),
                "roi_other_pct": to_pct(r["roi_other"]),
                "roi_diff_pct": to_pct(r["roi_diff"]),
                "roi_ci_lo_pct": to_pct(r["roi_ci_lo"]),
                "roi_ci_hi_pct": to_pct(r["roi_ci_hi"]),
                "roi_sig_up": r["roi_sig_up"],
                "roi_sig_down": r["roi_sig_down"],
                "hit_rate_pct": to_pct(r["hit_rate"]),
                "hit_rate_other_pct": to_pct(r["hit_rate_other"]),
                "hr_diff_pct": to_pct(r["hr_diff"]),
                "hr_ci_lo_pct": to_pct(r["hr_ci_lo"]),
                "hr_ci_hi_pct": to_pct(r["hr_ci_hi"]),
                "hr_sig_up": r["hr_sig_up"],
                "hr_sig_down": r["hr_sig_down"],
                "avg_odds": r["avg_odds"],
                "avg_odds_other": r["avg_odds_other"],
                "avg_payout_hit": r["avg_payout_hit"],
                "avg_payout_hit_other": r["avg_payout_hit_other"],
            })
        return {"feature": feature_key, "label": "", "rows": rows}

    race_table_list = []
    for fk, flabel in RACE_TABLE_FEATURES:
        d = build_feature_rows(fk)
        if d["rows"]:
            d["label"] = flabel
            race_table_list.append(d)
    single_list = []
    for fk, flabel in SINGLE_FEATURES:
        d = build_feature_rows(fk)
        if d["rows"]:
            d["label"] = flabel
            single_list.append(d)

    def sanitize(o):
        if isinstance(o, dict): return {k: sanitize(v) for k, v in o.items()}
        if isinstance(o, list): return [sanitize(v) for v in o]
        if hasattr(o, "item"): return o.item()
        return o

    out = sanitize({
        "n_samples": N,
        "K": K,
        "z_adj": z_adj,
        "race_table": race_table_list,
        "single": single_list,
        "generated_at": datetime.now().isoformat(),
    })
    with open("scratch/single_feature_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nsaved scratch/single_feature_result.json", flush=True)

    # Turso 保存
    try:
        url = os.getenv("TURSO_URL")
        token = os.getenv("TURSO_TOKEN")
        if url and token:
            http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
            client2 = libsql_client.create_client_sync(url=http_url, auth_token=token)
            client2.execute(
                "CREATE TABLE IF NOT EXISTS analytics_feature_cache ("
                "id INTEGER PRIMARY KEY,"
                "payload TEXT NOT NULL,"
                "updated_at TEXT NOT NULL)"
            )
            payload = json.dumps(out, ensure_ascii=False)
            client2.execute(
                "INSERT INTO analytics_feature_cache (id, payload, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
                [payload, datetime.now().isoformat()],
            )
            try:
                client2.close()
            except Exception:
                pass
            print("saved turso analytics_feature_cache", flush=True)
    except Exception as e:
        print(f"turso save fail: {e}", flush=True)


main()
import os as _o
_o._exit(0)
