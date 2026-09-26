"""単勝用 CART (numpyのみ)。
判定: 葉の ROI が 全体ROI(=市場ベースライン) を 95%CI で有意に上回るか。
"""
import os
import json
import math
import time
from collections import Counter
from datetime import datetime

import numpy as np
import libsql_client
from scipy import stats


FEATURES = [
    ("odds", "num"),
    ("pop", "num"),
    ("frame", "num"),
    ("weight", "num"),
    ("sex_id", "cat"),
    ("age", "num"),
    ("hw", "num"),
    ("hw_chg", "num"),
    ("hw_chg_abs", "num"),
    ("n_runners", "num"),
    ("distance", "num"),
    ("surface_id", "cat"),
    ("venue_id", "cat"),
    ("jockey_id", "cat"),
    ("odds_rank", "num"),
    ("pop_rank", "num"),
    ("is_first_fav", "cat"),
]


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

    # 騎手IDの採番（頻度上位20 + その他）
    r = client.execute("SELECT payload FROM scraped_races LIMIT 1000")
    jockey_counter = Counter()
    sample_rows = list(r.rows)
    for row in sample_rows:
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
    print(f"jockeys(top20): {top_jockeys[:5]}...", flush=True)

    X = []
    y = []
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

        # ランク付け用
        odds_list = sorted([r0.get("odds_win") or 99999 for r0 in runners])
        pop_list = sorted([r0.get("popularity") or 999 for r0 in runners])

        for r0 in runners:
            num = r0.get("horse_number")
            odds = r0.get("odds_win")
            pop = r0.get("popularity")
            frame = r0.get("frame_number")
            weight = r0.get("weight")
            hw = r0.get("horse_weight")
            hw_chg = r0.get("horse_weight_change")
            if num is None or odds is None or pop is None:
                continue
            # result_runnersから詳細
            sex_id = -1
            age = 0.0
            jockey_id = -1
            rr = next((x for x in result_runners if x.get("horse_number") == num), None)
            if rr:
                age_sex = rr.get("age_sex") or ""
                if age_sex:
                    if age_sex[0] == "牡": sex_id = 0
                    elif age_sex[0] == "牝": sex_id = 1
                    elif age_sex[0] == "セ": sex_id = 2
                    # 年齢抽出（数字部分）
                    import re as _re
                    m = _re.search(r"(\d+)", age_sex)
                    if m:
                        age = float(m.group(1))
                j = (rr.get("jockey") or "").strip()
                if j:
                    jockey_id = jockey_ids.get(j, len(jockey_ids))

            hw_chg_abs = abs(hw_chg) if hw_chg is not None else 0.0
            hw_chg_v = hw_chg if hw_chg is not None else 0.0
            hw_v = hw if hw is not None else 0.0

            odds_rank = odds_list.index(odds) + 1 if odds in odds_list else 99
            pop_rank = pop_list.index(pop) + 1 if pop in pop_list else 99
            is_first_fav = 1.0 if pop == 1 else 0.0

            payout = win_payouts.get(num, 0) if num == finish_order[0] else 0
            X.append([
                float(odds), float(pop), float(frame or 0), float(weight or 0),
                float(sex_id), float(age), float(hw_v), float(hw_chg_v),
                float(hw_chg_abs), float(n_runners), float(distance), float(surf_id),
                float(venue_id), float(jockey_id),
                float(odds_rank), float(pop_rank), float(is_first_fav),
            ])
            y.append(float(payout))
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(rows)} {time.time()-t0:.0f}s X={len(X)}", flush=True)

    try:
        client.close()
    except Exception:
        pass
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def best_split(X, y, idx, min_leaf):
    n = len(idx)
    if n < 2 * min_leaf:
        return None, -1.0
    best = None
    best_score = -1.0
    y_sub = y[idx]
    parent_var = np.var(y_sub) * n
    for f in range(X.shape[1]):
        col = X[idx, f]
        uniq = np.unique(col)
        if len(uniq) <= 1:
            continue
        if len(uniq) > 20:
            qs = np.linspace(0, 100, 21)[1:-1]
            cand = np.unique(np.percentile(col, qs))
        else:
            cand = (uniq[:-1] + uniq[1:]) / 2.0
        for th in cand:
            left_mask = col <= th
            n_l = int(left_mask.sum())
            if n_l < min_leaf or (n - n_l) < min_leaf:
                continue
            yl = y_sub[left_mask]
            yr = y_sub[~left_mask]
            score = parent_var - np.var(yl) * n_l - np.var(yr) * (n - n_l)
            if score > best_score:
                best_score = score
                best = (f, float(th))
    return best, best_score


def build_tree(X, y, idx, depth, max_depth, min_leaf):
    node = {"idx": idx, "n": len(idx), "depth": depth}
    if depth >= max_depth or len(idx) < 2 * min_leaf:
        return node
    split, score = best_split(X, y, idx, min_leaf)
    if split is None:
        return node
    f, th = split
    col = X[idx, f]
    left_mask = col <= th
    left_idx = idx[left_mask]
    right_idx = idx[~left_mask]
    if len(left_idx) < min_leaf or len(right_idx) < min_leaf:
        return node
    node["feature"] = f
    node["threshold"] = th
    node["left"] = build_tree(X, y, left_idx, depth + 1, max_depth, min_leaf)
    node["right"] = build_tree(X, y, right_idx, depth + 1, max_depth, min_leaf)
    return node


def collect_leaves(node, leaves=None):
    if leaves is None:
        leaves = []
    if "feature" not in node:
        leaves.append(node)
        return leaves
    collect_leaves(node["left"], leaves)
    collect_leaves(node["right"], leaves)
    return leaves


def traverse_with_path(node, feature_names, path=None, all_paths=None):
    if path is None:
        path = []
    if all_paths is None:
        all_paths = []
    if "feature" not in node:
        all_paths.append((node, list(path)))
        return all_paths
    f = node["feature"]
    th = node["threshold"]
    fname = feature_names[f]
    path.append((fname, "<=", th))
    traverse_with_path(node["left"], feature_names, path, all_paths)
    path.pop()
    path.append((fname, ">", th))
    traverse_with_path(node["right"], feature_names, path, all_paths)
    path.pop()
    return all_paths


def main():
    print("=== build_dataset ===", flush=True)
    X, y = build_dataset()
    print(f"X shape: {X.shape}", flush=True)
    print(f"y sum: {y.sum():.0f}  y>0: {(y>0).sum()}", flush=True)

    feature_names = [f[0] for f in FEATURES]

    # ベースライン（全体ROI）
    n_all = len(y)
    stake_all = n_all * 100
    payout_all = float(y.sum())
    base_roi = payout_all / stake_all
    profits_all = y / 100.0 - 1.0
    base_mean = profits_all.mean()
    base_se = profits_all.std(ddof=1) / math.sqrt(n_all)
    print(f"\nbaseline ROI: {base_roi:.4f}  mean={base_mean:.4f}  se={base_se:.5f}", flush=True)

    idx = np.arange(len(y))
    print("=== build_tree (depth=5, min_leaf=500) ===", flush=True)
    t0 = time.time()
    tree = build_tree(X, y, idx, 0, 5, 500)
    print(f"build_tree done {time.time()-t0:.0f}s", flush=True)

    paths = traverse_with_path(tree, feature_names)
    print(f"leaves: {len(paths)}", flush=True)
    k = len(paths)
    alpha = 0.05
    z_adj = stats.norm.ppf(1 - alpha / (2 * k)) if k > 0 else 1.96

    all_idx = np.arange(len(y))
    results = []
    for node, path in paths:
        n = node["n"]
        idx_leaf = node["idx"]
        # 補集合
        mask_leaf = np.zeros(len(y), dtype=bool)
        mask_leaf[idx_leaf] = True
        idx_other = all_idx[~mask_leaf]
        n_o = len(idx_other)
        if n_o == 0:
            continue
        stake = n * 100
        payout = float(y[idx_leaf].sum())
        profits = y[idx_leaf] / 100.0 - 1.0
        mean = float(profits.mean())
        se = float(profits.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
        # 補集合
        stake_o = n_o * 100
        payout_o = float(y[idx_other].sum())
        profits_o = y[idx_other] / 100.0 - 1.0
        mean_o = float(profits_o.mean())
        se_o = float(profits_o.std(ddof=1) / math.sqrt(n_o)) if n_o > 1 else 0.0
        diff = mean - mean_o
        se_diff = math.sqrt(se * se + se_o * se_o)
        ci_lo = diff - z_adj * se_diff
        ci_hi = diff + z_adj * se_diff
        results.append({
            "path": path,
            "n": n,
            "roi": payout / stake,
            "mean_profit": mean,
            "n_other": n_o,
            "roi_other": payout_o / stake_o,
            "mean_profit_other": mean_o,
            "diff_mean": diff,
            "ci_lo": float(ci_lo),
            "ci_hi": float(ci_hi),
            "payout": payout,
        })

    sig = [r for r in results if r["ci_lo"] > 0]
    sig.sort(key=lambda r: r["diff_mean"], reverse=True)

    print(f"\n=== Bonferroni z_adj = {z_adj:.3f} (k={k}) ===")
    print(f"補集合を有意に上回る葉: {len(sig)} / {len(results)}\n")

    for r in sig[:20]:
        print(f"ROI={r['roi']:.4f} diff={r['diff_mean']:+.4f} n={r['n']} "
              f"CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}]")
        for (fname, op, th) in r["path"]:
            print(f"    {fname} {op} {th}")
        print()

    # 全葉も参考に表示（差の大きい順）
    all_sorted = sorted(results, key=lambda r: r["diff_mean"], reverse=True)
    print("\n=== 参考: 差の大きい上位10葉（有意でなくても） ===")
    for r in all_sorted[:10]:
        print(f"ROI={r['roi']:.4f} diff={r['diff_mean']:+.4f} n={r['n']} CI_lo={r['ci_lo']:.4f}")

    def _f(v):
        try:
            return float(v)
        except Exception:
            return v

    def sanitize(obj):
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [sanitize(v) for v in obj]
        if hasattr(obj, "item"):
            return obj.item()
        return obj

    out = sanitize({
        "leaves": results,
        "significant": sig,
        "z_adj": z_adj,
        "k": k,
        "baseline_roi": base_roi,
        "baseline_mean": base_mean,
        "baseline_se": base_se,
        "n_samples": n_all,
        "generated_at": datetime.now().isoformat(),
    })
    with open("scratch/cart_single_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nsaved scratch/cart_single_result.json", flush=True)

    fc = Counter()
    for r in results:
        for (fname, op, th) in r["path"]:
            fc[fname] += 1
    print("\n=== 特徴量使用回数 ===")
    for name, cnt in fc.most_common():
        print(f"  {name}: {cnt}")


main()
import os as _o
_o._exit(0)
