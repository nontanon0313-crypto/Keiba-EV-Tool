"""券種別検証。コマンドライン引数で券種を指定。

使い方:
  PYTHONPATH=. python3 scratch/multi_ticket_verify.py quinella
  PYTHONPATH=. python3 scratch/multi_ticket_verify.py wide
  PYTHONPATH=. python3 scratch/multi_ticket_verify.py exacta
  PYTHONPATH=. python3 scratch/multi_ticket_verify.py trio
  PYTHONPATH=. python3 scratch/multi_ticket_verify.py trifecta

設計:
- 各サンプル（= 1買い目）を、特徴ごとに1つのビンに分類
- 検定:
    (1) B vs B^c: 特徴FのビンL vs それ以外
    (2) 実 vs 市場: 各サンプルの (的中 - 市場確率) と (実利益 - 市場利益) の平均

市場的中率_i = (1 - rho_race) / odds_i
rho_race = 1 - HITS_PER_RACE[ticket] / Σ(1/odds)

除外:
- 50.0（旧パーサ痕跡）を含むレース
- odds=1.0（元返し）を含むレース
"""
import os
import sys
import json
import math
import re as _re
import time
import pickle
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

import numpy as np
import libsql_client
from scipy import stats

from backend.constants import (
    STAKE_PER_BET, HITS_PER_RACE, ODDS_MISSING_LEGACY, JOCKEY_TOP_N,
    AGE_BINS, WEIGHT_BINS, HW_CHG_BINS, POP_BINS, WIN_ODDS_BINS, HORSE_WEIGHT_BINS,
    DISTANCE_BINS, EXCLUDED_TRACK_CODES, TRACK_CD_TO_VENUE,
)


TICKET_JP = {
    "quinella": "馬連", "wide": "ワイド", "exacta": "馬単",
    "trio": "3連複", "trifecta": "3連単",
}


def new_acc():
    """1ビン分の累積値。サンプルリストを持たない。"""
    return {
        "n": 0,
        "sum_hit": 0.0,
        "sum_prob": 0.0,
        "sum_payout": 0.0,
        "sum_profit": 0.0,
        "sum_profit_sq": 0.0,
        "sum_hr_diff": 0.0,
        "sum_hr_diff_sq": 0.0,
        "sum_roi_diff": 0.0,
        "sum_roi_diff_sq": 0.0,
    }


def acc_add(acc, market_prob, odds, hit, payout, rho_race):
    profit = payout / STAKE_PER_BET - 1.0
    hr_diff = float(hit) - market_prob
    roi_diff = profit + rho_race
    acc["n"] += 1
    acc["sum_hit"] += hit
    acc["sum_prob"] += market_prob
    acc["sum_payout"] += payout
    acc["sum_profit"] += profit
    acc["sum_profit_sq"] += profit * profit
    acc["sum_hr_diff"] += hr_diff
    acc["sum_hr_diff_sq"] += hr_diff * hr_diff
    acc["sum_roi_diff"] += roi_diff
    acc["sum_roi_diff_sq"] += roi_diff * roi_diff


def acc_sub(a, b):
    """a - b を返す（B^c を求めるため）。"""
    out = {}
    for k in a:
        out[k] = a[k] - b[k]
    return out


def acc_stats(acc):
    """累積値から統計量を計算。"""
    n = acc["n"]
    if n == 0:
        return None
    mean_roi = acc["sum_payout"] / (n * STAKE_PER_BET) - 1.0
    mean_market_hr = acc["sum_prob"] / n
    mean_real_hr = acc["sum_hit"] / n
    mean_profit = acc["sum_profit"] / n
    var_profit = (acc["sum_profit_sq"] / n) - (mean_profit * mean_profit)
    var_profit = max(var_profit, 0.0)
    se_roi = math.sqrt(var_profit / n) if n > 0 else 0.0
    mean_hr_diff = acc["sum_hr_diff"] / n
    var_hr_diff = (acc["sum_hr_diff_sq"] / n) - (mean_hr_diff * mean_hr_diff)
    var_hr_diff = max(var_hr_diff, 0.0)
    se_hr_diff = math.sqrt(var_hr_diff / n) if n > 0 else 0.0
    # 実的中率そのもののSE (二項分布近似)
    se_real_hr = math.sqrt(mean_real_hr * (1 - mean_real_hr) / n) if n > 0 else 0.0
    mean_roi_diff = acc["sum_roi_diff"] / n
    var_roi_diff = (acc["sum_roi_diff_sq"] / n) - (mean_roi_diff * mean_roi_diff)
    var_roi_diff = max(var_roi_diff, 0.0)
    se_roi_diff = math.sqrt(var_roi_diff / n) if n > 0 else 0.0
    return {
        "n": n,
        "roi": mean_roi,
        "market_hr": mean_market_hr,
        "real_hr": mean_real_hr,
        "se": se_roi,
        "se_hr": se_hr_diff,
        "mean_hr_diff": mean_hr_diff,
        "se_hr_vm": se_hr_diff,
        "mean_roi_diff": mean_roi_diff,
        "se_roi_vm": se_roi_diff,
        "se_real_hr": se_real_hr,
    }
SEX_LABEL = {0: "牡", 1: "牝", 2: "セ", -1: "不明"}


def classify(value, bins, fmt):
    for lo, hi in bins:
        if lo <= value < hi:
            return fmt(lo, hi)
    return None


def race_has_bad_odds(runners):
    for r0 in runners:
        o = r0.get("odds_win")
        if o == ODDS_MISSING_LEGACY or o == 1.0:
            return True
    return False


def build_jockey_ids(client):
    r = client.execute("SELECT payload FROM scraped_races LIMIT 1000")
    counter = Counter()
    for row in r.rows:
        try:
            p = json.loads(row[0])
        except Exception:
            continue
        for rr in p.get("result_runners", []):
            j = (rr.get("jockey") or "").strip()
            if j:
                counter[j] += 1
    top = [j for j, _ in counter.most_common(JOCKEY_TOP_N)]
    return {j: i for i, j in enumerate(top)}


def combo_to_nums(ticket, combo):
    """コンボ文字列を頭数のリストに変換。順序は券種依存。"""
    try:
        nums = [int(x) for x in combo.split("-")]
    except ValueError:
        return None
    if len(nums) < 2:
        return None
    return nums


def canonical_combo(ticket, nums):
    """順不同の券種はソート済みキーを返す。順序ありなら元の順。"""
    if ticket in ("quinella", "wide", "trio"):
        return "-".join(str(x) for x in sorted(nums))
    return "-".join(str(x) for x in nums)


def hit_check(ticket, combo_nums, finish_order):
    if ticket == "quinella":
        if len(finish_order) < 2: return 0
        return 1 if sorted(combo_nums) == sorted(finish_order[:2]) else 0
    if ticket == "wide":
        if len(finish_order) < 3: return 0
        w = finish_order[:3]
        s = sorted(combo_nums)
        pairs = [sorted([w[0], w[1]]), sorted([w[0], w[2]]), sorted([w[1], w[2]])]
        return 1 if s in pairs else 0
    if ticket == "exacta":
        if len(finish_order) < 2: return 0
        return 1 if combo_nums == finish_order[:2] else 0
    if ticket == "trio":
        if len(finish_order) < 3: return 0
        return 1 if sorted(combo_nums) == sorted(finish_order[:3]) else 0
    if ticket == "trifecta":
        if len(finish_order) < 3: return 0
        return 1 if combo_nums == finish_order[:3] else 0
    return 0


def find_payout(payouts, ticket_jp, hit_combo_nums, ticket):
    """的中した払戻円を取得。"""
    canonical = canonical_combo(ticket, hit_combo_nums)
    rows = payouts.get(ticket_jp) or []
    for prow in rows:
        if isinstance(prow, list) and len(prow) >= 3:
            try:
                combo_p = prow[1]
                amt = int(prow[2].replace(",", "").replace("円", ""))
                parts = combo_p.split("-")
                if ticket in ("quinella", "wide", "trio"):
                    key = "-".join(sorted(parts, key=lambda x: int(x)))
                else:
                    key = "-".join(parts)
                if key == canonical:
                    return amt
            except Exception:
                pass
    return 0


def build_feature_tags(rec, num_order, runner_map, rr_map, jockey_ids):
    """num_order: 構成馬の馬番リスト（券種に応じた順序）。
    1頭目を win1、2頭目を win2、3頭目を win3 としてタグ付け。"""
    tags = {}
    tags["distance"] = classify(rec["distance"], DISTANCE_BINS, lambda lo, hi: f"{lo}-{hi}")
    tags["n_runners"] = f"{rec['n_runners']}頭"
    tags["surface"] = {0: "ダート", 1: "芝", 2: "障害"}[rec["surface_id"]]
    tags["venue"] = rec["venue"]

    for pos, num in enumerate(num_order, 1):
        prefix = f"win{pos}_"
        r0 = runner_map.get(num)
        rr = rr_map.get(num)
        if r0 is None:
            continue
        age = 0.0
        sex_id = -1
        if rr:
            age_sex = rr.get("age_sex") or ""
            if age_sex:
                if age_sex[0] == "牡": sex_id = 0
                elif age_sex[0] == "牝": sex_id = 1
                elif age_sex[0] == "セ": sex_id = 2
                m = _re.search(r"(\d+)", age_sex)
                if m:
                    age = float(m.group(1))
        tags[prefix + "age"] = classify(age, AGE_BINS, lambda lo, hi: f"{lo}-{hi-1}歳")
        tags[prefix + "sex"] = SEX_LABEL[sex_id]

        weight = (rr.get("weight") if rr else None) or r0.get("weight")
        if weight is not None:
            tags[prefix + "weight"] = classify(float(weight), WEIGHT_BINS, lambda lo, hi: f"{lo}-{hi}")
        hw = (rr.get("horse_weight") if rr else None) or r0.get("horse_weight")
        if hw is not None:
            tags[prefix + "hw"] = classify(float(hw), HORSE_WEIGHT_BINS, lambda lo, hi: f"{lo}-{hi}")
        hc = rr.get("horse_weight_change") if rr else None
        if hc is not None:
            tags[prefix + "hw_chg"] = classify(float(hc), HW_CHG_BINS, lambda lo, hi: f"{lo}~{hi}")
        pop = (rr.get("popularity") if rr else None) or r0.get("popularity")
        if pop is not None:
            p = int(pop)
            for lo, hi, name in POP_BINS:
                if lo <= p < hi:
                    tags[prefix + "pop"] = name
                    break
        wo = r0.get("odds_win")
        if wo is not None and wo > 1:
            tags[prefix + "win_odds"] = classify(float(wo), WIN_ODDS_BINS, lambda lo, hi: f"{lo}-{hi}")
        fr = r0.get("frame_number")
        if fr is not None:
            tags[prefix + "frame"] = f"枠{int(fr)}"
        jockey_id = -1
        if rr:
            j = (rr.get("jockey") or "").strip()
            if j in jockey_ids:
                jockey_id = jockey_ids[j]
        tags[prefix + "jockey"] = f"騎手{jockey_id}" if jockey_id >= 0 else "その他騎手"

    return tags


CHECKPOINT_INTERVAL = 500


def checkpoint_dir(ticket):
    d = Path(f"scratch/checkpoint_{ticket}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_checkpoint(ticket, feature_data, processed_upto):
    d = checkpoint_dir(ticket)
    with open(d / "feature_data.pkl", "wb") as f:
        pickle.dump(dict(feature_data), f)
    with open(d / "progress.json", "w", encoding="utf-8") as f:
        json.dump({"processed_upto": processed_upto}, f)
    print(f"  [checkpoint] saved at {processed_upto}", flush=True)


def load_checkpoint(ticket):
    d = checkpoint_dir(ticket)
    pkl = d / "feature_data.pkl"
    prog = d / "progress.json"
    if not pkl.exists() or not prog.exists():
        return None, 0
    try:
        with open(pkl, "rb") as f:
            feature_data = pickle.load(f)
        with open(prog, "r", encoding="utf-8") as f:
            info = json.load(f)
        processed = info.get("processed_upto", 0)
        print(f"[checkpoint] 復元: {processed} レース分", flush=True)
        return feature_data, processed
    except Exception as e:
        print(f"[checkpoint] 復元失敗: {e}", flush=True)
        return None, 0


def clear_checkpoint(ticket):
    import shutil
    d = checkpoint_dir(ticket)
    try:
        shutil.rmtree(d)
        print(f"[checkpoint] 削除", flush=True)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print("usage: multi_ticket_verify.py <ticket>")
        print("ticket: quinella | wide | exacta | trio | trifecta")
        return
    ticket = sys.argv[1]
    if ticket not in TICKET_JP:
        print(f"unknown ticket: {ticket}")
        return
    ticket_jp = TICKET_JP[ticket]

    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    print(f"=== ticket: {ticket} ({ticket_jp}) ===", flush=True)
    jockey_ids = build_jockey_ids(client)
    print(f"top {len(jockey_ids)} jockeys", flush=True)

    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    race_rows = list(r.rows)
    print(f"races: {len(race_rows)}", flush=True)

    # オッズは500件ずつのチャンクで取得（メモリ抑制 + N+1回避）
    from backend.app.services import odds_store

    feature_data_loaded, processed_upto = load_checkpoint(ticket)
    if feature_data_loaded is not None:
        feature_data = defaultdict(lambda: defaultdict(new_acc))
        for feat, bins in feature_data_loaded.items():
            for label, acc in bins.items():
                feature_data[feat][label] = acc
        start_idx = processed_upto
    else:
        feature_data = defaultdict(lambda: defaultdict(new_acc))
        start_idx = 0

    n_races_used = 0
    n_samples = 0
    n_skip_bad = 0

    t0 = time.time()
    CHUNK_SIZE = 500
    odds_batch = {}
    current_chunk = -1

    for i, row in enumerate(race_rows):
        if i < start_idx:
            continue
        # 500件ごとに新しいチャンクのオッズを取得
        chunk_idx = i // CHUNK_SIZE
        if chunk_idx != current_chunk:
            current_chunk = chunk_idx
            chunk_start = chunk_idx * CHUNK_SIZE
            chunk_end = min(chunk_start + CHUNK_SIZE, len(race_rows))
            chunk_rids = [r[0] for r in race_rows[chunk_start:chunk_end]]
            odds_batch = odds_store.get_odds_batch(chunk_rids)
            print(f"  [odds chunk] {chunk_start}-{chunk_end} loaded={len(odds_batch)}", flush=True)
        rid = row[0]
        parts_rid = rid.split("-")
        if len(parts_rid) >= 3 and parts_rid[2] in EXCLUDED_TRACK_CODES:
            continue
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        runners = p.get("runners", [])
        result_runners = p.get("result_runners", [])
        finish_order = p.get("finish_order") or []
        payouts = p.get("payouts") or {}
        if not runners or len(finish_order) < 2:
            continue
        if ticket in ("trio", "trifecta") and len(finish_order) < 3:
            continue
        if race_has_bad_odds(runners):
            n_skip_bad += 1
            continue

        odds_payload = odds_batch.get(rid)
        if not odds_payload:
            continue
        odds_map = odds_payload.get(ticket) or {}
        if not odds_map:
            continue

        # Σ(1/odds)
        inv_sum = 0.0
        for combo, e in odds_map.items():
            if ticket == "wide":
                o = e.get("min")
            else:
                o = e.get("odds")
            if o and o > 1:
                inv_sum += 1.0 / float(o)
        if inv_sum <= 0:
            continue
        rho_race = 1.0 - HITS_PER_RACE[ticket] / inv_sum
        market_factor = 1.0 - rho_race

        parts = rid.split("-")
        rec = {
            "distance": p.get("distance") or 0,
            "surface_id": {"ダート":0,"芝":1,"障害":2}.get(p.get("surface") or "ダート", 0),
            "n_runners": len(runners),
            "venue": TRACK_CD_TO_VENUE.get(parts[2] if len(parts) >= 3 else "", "不明"),
        }
        runner_map = {r0.get("horse_number"): r0 for r0 in runners}
        rr_map = {rr.get("horse_number"): rr for rr in result_runners}

        # 的中判定
        hit_nums = finish_order[:3] if ticket in ("trio", "trifecta") else finish_order[:2]
        hit_payout = find_payout(payouts, ticket_jp, hit_nums, ticket)

        for combo, e in odds_map.items():
            if ticket == "wide":
                o = e.get("min")
            else:
                o = e.get("odds")
            if not o or o <= 1:
                continue
            o = float(o)
            nums = combo_to_nums(ticket, combo)
            if nums is None or len(nums) < 2:
                continue
            ra = runner_map.get(nums[0])
            if ra is None:
                continue
            # 券種ごとの順序: 番号順 or 着順
            # 保存されている combo の順序をそのまま使う（馬連/ワイド/3連複はソート済み、
            # 馬単/3連単は着順）。ただし馬連等は念のためソート
            if ticket in ("quinella", "wide", "trio"):
                num_order = sorted(nums)
            else:
                num_order = nums

            market_prob = market_factor / o
            is_hit = hit_check(ticket, nums, finish_order)
            payout = hit_payout if is_hit else 0

            tags = build_feature_tags(rec, num_order, runner_map, rr_map, jockey_ids)
            for feature, label in tags.items():
                if label is None:
                    continue
                acc_add(feature_data[feature][label], market_prob, o, is_hit, payout, rho_race)
            n_samples += 1

        n_races_used += 1
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(race_rows)} {time.time()-t0:.0f}s samples={n_samples}", flush=True)
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            save_checkpoint(ticket, feature_data, i + 1)

    print(f"\n=== 集計: {n_races_used} レース, {n_samples} サンプル, 除外(50/1.0)={n_skip_bad} ===", flush=True)

    # 特徴ごとに B vs B^c 検定（累積値ベース）
    def aggregate_bins(bins):
        total = new_acc()
        for label, acc in bins.items():
            for k in total:
                total[k] += acc[k]
        return total

    total_bins = sum(len(b) for b in feature_data.values())
    z_adj = stats.norm.ppf(1 - 0.05 / (2 * total_bins)) if total_bins > 0 else 1.96
    print(f"\n総検定数={total_bins}, z_adj={z_adj:.4f}", flush=True)

    results = {}
    for feature, bins in feature_data.items():
        feature_results = []
        total_acc = aggregate_bins(bins)
        for label, acc in bins.items():
            stats_B = acc_stats(acc)
            if stats_B is None or stats_B["n"] < 100:
                continue
            other_acc = acc_sub(total_acc, acc)
            stats_C = acc_stats(other_acc)
            if stats_C is None or stats_C["n"] < 100:
                continue
            roi_diff = stats_B["roi"] - stats_C["roi"]
            hr_diff = stats_B["real_hr"] - stats_C["real_hr"]
            se_roi = math.sqrt(stats_B["se"]**2 + stats_C["se"]**2)
            se_hr = math.sqrt(stats_B["se_hr"]**2 + stats_C["se_hr"]**2)
            roi_ci_lo = roi_diff - z_adj * se_roi
            roi_ci_hi = roi_diff + z_adj * se_roi
            hr_ci_lo = hr_diff - z_adj * se_hr
            hr_ci_hi = hr_diff + z_adj * se_hr

            hr_vm_mean = stats_B["mean_hr_diff"]
            hr_vm_se = stats_B["se_hr_vm"]
            hr_vm_ci_lo = hr_vm_mean - z_adj * hr_vm_se
            hr_vm_ci_hi = hr_vm_mean + z_adj * hr_vm_se
            roi_vm_mean = stats_B["mean_roi_diff"]
            roi_vm_se = stats_B["se_roi_vm"]
            roi_vm_ci_lo = roi_vm_mean - z_adj * roi_vm_se
            roi_vm_ci_hi = roi_vm_mean + z_adj * roi_vm_se

            # 実値そのものの95%CI (z=1.96、B と B^c)
            z_std = 1.96
            roi_b_ci_lo = (stats_B["roi"] - z_std * stats_B["se"]) * 100
            roi_b_ci_hi = (stats_B["roi"] + z_std * stats_B["se"]) * 100
            roi_c_ci_lo = (stats_C["roi"] - z_std * stats_C["se"]) * 100
            roi_c_ci_hi = (stats_C["roi"] + z_std * stats_C["se"]) * 100
            hr_b_ci_lo = (stats_B["real_hr"] - z_std * stats_B["se_real_hr"]) * 100
            hr_b_ci_hi = (stats_B["real_hr"] + z_std * stats_B["se_real_hr"]) * 100
            hr_c_ci_lo = (stats_C["real_hr"] - z_std * stats_C["se_real_hr"]) * 100
            hr_c_ci_hi = (stats_C["real_hr"] + z_std * stats_C["se_real_hr"]) * 100

            feature_results.append({
                "label": label, "n": stats_B["n"], "n_other": stats_C["n"],
                "roi": stats_B["roi"], "roi_other": stats_C["roi"],
                "roi_b_ci_lo": float(roi_b_ci_lo), "roi_b_ci_hi": float(roi_b_ci_hi),
                "roi_c_ci_lo": float(roi_c_ci_lo), "roi_c_ci_hi": float(roi_c_ci_hi),
                "roi_diff": roi_diff, "roi_ci_lo": roi_ci_lo, "roi_ci_hi": roi_ci_hi,
                "roi_sig_up": roi_ci_lo > 0, "roi_sig_down": roi_ci_hi < 0,
                "real_hr": stats_B["real_hr"], "real_hr_other": stats_C["real_hr"],
                "hr_b_ci_lo": float(hr_b_ci_lo), "hr_b_ci_hi": float(hr_b_ci_hi),
                "hr_c_ci_lo": float(hr_c_ci_lo), "hr_c_ci_hi": float(hr_c_ci_hi),
                "market_hr": stats_B["market_hr"], "market_hr_other": stats_C["market_hr"],
                "hr_diff": hr_diff, "hr_ci_lo": hr_ci_lo, "hr_ci_hi": hr_ci_hi,
                "hr_sig_up": hr_ci_lo > 0, "hr_sig_down": hr_ci_hi < 0,
                "roi_vm_mean": roi_vm_mean,
                "roi_vm_ci_lo": float(roi_vm_ci_lo), "roi_vm_ci_hi": float(roi_vm_ci_hi),
                "roi_vm_sig_up": roi_vm_ci_lo > 0, "roi_vm_sig_down": roi_vm_ci_hi < 0,
                "hr_vm_mean": hr_vm_mean,
                "hr_vm_ci_lo": float(hr_vm_ci_lo), "hr_vm_ci_hi": float(hr_vm_ci_hi),
                "hr_vm_sig_up": hr_vm_ci_lo > 0, "hr_vm_sig_down": hr_vm_ci_hi < 0,
            })
        results[feature] = feature_results


    def sanitize(o):
        if isinstance(o, dict): return {k: sanitize(v) for k, v in o.items()}
        if isinstance(o, list): return [sanitize(v) for v in o]
        if hasattr(o, "item"): return o.item()
        return o

    out = sanitize({
        "ticket": ticket, "ticket_jp": ticket_jp,
        "n_races": n_races_used, "n_samples": n_samples,
        "z_adj": z_adj, "total_bins": total_bins,
        "results": results,
        "generated_at": datetime.now().isoformat(),
    })
    out_path = f"scratch/multi_{ticket}_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"saved {out_path}", flush=True)

    clear_checkpoint(ticket)

    print("\n=== 実 vs 市場: ROI 優位（実 > 市場） ===", flush=True)
    for feature, rs in results.items():
        for r in rs:
            if r["roi_vm_sig_up"]:
                print(f"  [{feature}] {r['label']} n={r['n']} diff={r['roi_vm_mean']*100:+.3f}%", flush=True)
    print("\n=== 実 vs 市場: 的中率 優位（実 > 市場） ===", flush=True)
    for feature, rs in results.items():
        for r in rs:
            if r["hr_vm_sig_up"]:
                print(f"  [{feature}] {r['label']} n={r['n']} diff={r['hr_vm_mean']*100:+.3f}%", flush=True)

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
