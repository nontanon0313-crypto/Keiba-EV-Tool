"""Plackett-Luce モデルを features テーブルから学習する。

スコア: score_i = log(market_prob_i) + w · x_i
レース内 softmax: P(i が1着) = softmax(score_i)
損失: -log P(winner) + λ ||w||^2
最適化: Adam

市場確率を出発点に、検証済みの特徴量で補正する「市場ベース＋残差補正」方式。
時系列分割: 2023-2024 で学習、2025 で評価。

使い方:
    python3 -m backend.scripts.train_pl_model
    python3 -m backend.scripts.train_pl_model limit=1000
"""
import os
import json
import time
import math
from datetime import datetime

import numpy as np
import libsql_client

LOG_PATH = "train_pl.log"

FEATURE_KEYS = [
    "win_rate", "place_rate", "show_rate", "avg_finish",
    "avg_agari_3f", "best_agari_3f", "avg_time_norm", "best_time_norm",
    "recent1_finish", "recent1_agari",
    "recent3_avg_finish", "recent5_avg_finish", "recent5_avg_agari",
    "same_dist_place_rate", "same_cond_place_rate",
    "same_venue_place_rate", "same_surface_place_rate",
    "same_dist_avg_finish",
    "days_since_last", "horse_weight_trend", "avg_corner_ratio",
    "weight", "horse_weight",
]

INTERACTIONS = [
    ("dist_x_cond", "same_dist_place_rate", "same_cond_place_rate"),
    ("dist_x_weight", "same_dist_place_rate", "weight"),
    ("recent_x_dist", "recent3_avg_finish", "same_dist_place_rate"),
    ("corner_x_weight", "avg_corner_ratio", "weight"),
    ("weight_x_hw", "weight", "horse_weight"),
    ("agari_x_time", "avg_agari_3f", "avg_time_norm"),
    ("venue_x_dist", "same_venue_place_rate", "same_dist_place_rate"),
    ("winrate_x_dist", "win_rate", "same_dist_place_rate"),
]

ALL_KEYS = list(FEATURE_KEYS) + [x[0] for x in INTERACTIONS]

# 特徴量セットのプリセット
PRESETS = {
    "all": {
        "features": FEATURE_KEYS,
        "interactions": INTERACTIONS,
    },
    "condition": {
        "features": [
            "same_dist_place_rate", "same_cond_place_rate",
            "same_venue_place_rate", "same_surface_place_rate",
            "same_dist_avg_finish", "days_since_last",
        ],
        "interactions": [],
    },
    "style": {
        "features": ["avg_corner_ratio"],
        "interactions": [],
    },
    "ability": {
        "features": [
            "win_rate", "place_rate", "show_rate", "avg_finish",
            "avg_agari_3f", "best_agari_3f", "avg_time_norm", "best_time_norm",
            "recent1_finish", "recent1_agari",
            "recent3_avg_finish", "recent5_avg_finish", "recent5_avg_agari",
        ],
        "interactions": [],
    },
    "state": {
        "features": ["weight", "horse_weight", "horse_weight_trend", "days_since_last"],
        "interactions": [],
    },
}

STATS = {}


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def load_data(limit=None):
    """features と scraped_races から (rid, date, runners, winner) のリストを作る。"""
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        per_race = {}
        r = c.execute("SELECT DISTINCT race_id FROM features ORDER BY race_id")
        all_rids = [row[0] for row in r.rows]
        _log("distinct races: " + str(len(all_rids)))
        CHUNK = 200
        for i in range(0, len(all_rids), CHUNK):
            chunk = all_rids[i:i+CHUNK]
            ph = ",".join(["?"] * len(chunk))
            r2 = c.execute(
                "SELECT race_id, horse_number, features_json FROM features WHERE race_id IN (" + ph + ")",
                chunk,
            )
            for row in r2.rows:
                rid = row[0]
                num = int(row[1])
                try:
                    f = json.loads(row[2])
                except Exception:
                    continue
                if rid not in per_race:
                    per_race[rid] = []
                per_race[rid].append((num, f))
            if i % 2000 == 0:
                _log("features loaded: " + str(i + CHUNK) + "/" + str(len(all_rids)))
        _log("races loaded: " + str(len(per_race)))

        winners = {}
        race_dates = {}
        last_rid = ""
        PAGE = 500
        while True:
            r2 = c.execute(
                "SELECT race_id, json_extract(payload, '$.finish_order[0]'), json_extract(payload, '$.date') FROM scraped_races "
                "WHERE race_id > ? ORDER BY race_id LIMIT ?",
                [last_rid, PAGE],
            )
            rows = list(r2.rows)
            if not rows:
                break
            for row in rows:
                rid = row[0]
                w = row[1]
                dt = row[2]
                if dt:
                    race_dates[rid] = dt
                if w is None:
                    continue
                try:
                    winners[rid] = int(w)
                except (ValueError, TypeError):
                    continue
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
        _log("winners loaded: " + str(len(winners)))

        samples = []
        for rid, runners in per_race.items():
            if rid not in winners:
                continue
            w = winners[rid]
            nums = [n for n, _ in runners]
            if w not in nums:
                continue
            samples.append((rid, race_dates.get(rid, ""), runners, w))
            if limit and len(samples) >= limit:
                break
        return samples
    finally:
        try:
            c.close()
        except Exception:
            pass


def build_matrix(samples, feature_keys=None, interactions=None):
    """各サンプルを (X (n×d), market_log (n), winner_idx, date) に変換。

    feature_keys, interactions を指定しない場合は FEATURE_KEYS, INTERACTIONS（all）を使う。
    """
    if feature_keys is None:
        feature_keys = FEATURE_KEYS
    if interactions is None:
        interactions = INTERACTIONS

    # STATS は全プリセット共通で全 FEATURE_KEYS 分計算（他プリセットでも再利用可能に）
    all_vals = {k: [] for k in FEATURE_KEYS}
    for rid, dt, runners, w in samples:
        for num, f in runners:
            for k in FEATURE_KEYS:
                v = _to_num(f.get(k))
                if v is not None:
                    all_vals[k].append(v)
    for k in FEATURE_KEYS:
        arr = np.array(all_vals[k], dtype=np.float64)
        if len(arr) == 0:
            STATS[k] = (0.0, 1.0)
            continue
        mu = float(arr.mean())
        sd = float(arr.std())
        if sd < 1e-9:
            sd = 1.0
        STATS[k] = (mu, sd)
    _log("stats computed for all FEATURE_KEYS")

    total_d = len(feature_keys) + len(interactions)
    out = []
    for rid, dt, runners, w in samples:
        n = len(runners)
        X = np.zeros((n, total_d), dtype=np.float64)
        market_log = np.zeros(n, dtype=np.float64)
        wi = -1
        inv_sum = 0.0
        for i, (num, f) in enumerate(runners):
            ow = _to_num(f.get("odds_win"))
            if ow and ow > 0:
                inv_sum += 1.0 / ow
        for i, (num, f) in enumerate(runners):
            if num == w:
                wi = i
            base_norm = {}
            for j, k in enumerate(feature_keys):
                v = _to_num(f.get(k))
                if v is None:
                    v = STATS.get(k, (0.0, 1.0))[0]
                mu, sd = STATS.get(k, (0.0, 1.0))
                nb = (v - mu) / sd
                X[i, j] = nb
                base_norm[k] = nb
            for j, (name, k1, k2) in enumerate(interactions):
                X[i, len(feature_keys) + j] = base_norm.get(k1, 0.0) * base_norm.get(k2, 0.0)
            ow = _to_num(f.get("odds_win"))
            if ow and ow > 0 and inv_sum > 0:
                p_mkt = (1.0 / ow) / inv_sum
                market_log[i] = math.log(max(p_mkt, 1e-12))
            else:
                market_log[i] = math.log(1.0 / n) if n > 0 else -30.0
        if wi < 0:
            continue
        out.append((X, market_log, wi, dt))
    return out


def split_train_test(matrices, test_cutoff="2025-01-01"):
    """日付で train/test に分割。(X, market_log, wi) のみ残す。"""
    train_set = []
    test_set = []
    for item in matrices:
        X, market_log, wi = item[0], item[1], item[2]
        dt = item[3] if len(item) > 3 else ""
        if dt and dt >= test_cutoff:
            test_set.append((X, market_log, wi))
        else:
            train_set.append((X, market_log, wi))
    return train_set, test_set


def eval_loss(w, matrices, use_market=True):
    """w 固定での平均損失。use_market=True: scores = market_log + X @ w、False: X @ w。"""
    if not matrices:
        return float("nan")
    total = 0.0
    n = len(matrices)
    for X, market_log, wi in matrices:
        scores = (market_log + X @ w) if use_market else (X @ w)
        scores -= scores.max()
        ex = np.exp(scores)
        p = ex / ex.sum()
        total += -math.log(max(p[wi], 1e-12))
    return total / n


def train(matrices, epochs=200, lr=0.05, l2=1e-4, use_market=True, d=None):
    if d is None:
        d = len(ALL_KEYS)
    w = np.zeros(d, dtype=np.float64)
    m = np.zeros(d, dtype=np.float64)
    v = np.zeros(d, dtype=np.float64)
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    t = 0
    n = len(matrices)
    loss_history = []
    _log("training start: n=" + str(n) + " d=" + str(d))
    for ep in range(epochs):
        perm = np.random.permutation(n)
        total_loss = 0.0
        for idx in perm:
            X, market_log, wi = matrices[idx]
            scores = (market_log + X @ w) if use_market else (X @ w)
            scores -= scores.max()
            exp_s = np.exp(scores)
            ssum = exp_s.sum()
            P = exp_s / ssum
            total_loss += -math.log(max(P[wi], 1e-12))
            grad = P @ X - X[wi] + 2 * l2 * w
            t += 1
            m = beta1 * m + (1 - beta1) * grad
            v = beta2 * v + (1 - beta2) * (grad * grad)
            m_hat = m / (1 - beta1 ** t)
            v_hat = v / (1 - beta2 ** t)
            w -= lr * m_hat / (np.sqrt(v_hat) + eps)
        avg_loss = total_loss / n
        loss_history.append(round(avg_loss, 5))
        if (ep + 1) % 10 == 0 or ep == 0 or ep == epochs - 1:
            _log("epoch " + str(ep + 1) + "/" + str(epochs) + " loss=" + str(round(avg_loss, 5)))
    return w, loss_history


def save_params(w, stats, loss_history=None, model_id="pl", model_name="plackett-luce-v6-market-based", feature_keys=None):
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS model_params ("
            "id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        payload = {
            "model": model_name,
            "feature_keys": feature_keys if feature_keys is not None else ALL_KEYS,
            "weights": w.tolist(),
            "stats": {k: list(v) for k, v in stats.items()},
            "trained_at": datetime.now().isoformat(),
            "loss_history": loss_history or [],
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO model_params (id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
            [model_id, pj, datetime.now().isoformat()],
        )
        _log("params saved")
    finally:
        try:
            c.close()
        except Exception:
            pass


def main():
    import sys
    limit = None
    use_market = True
    preset_name = "all"
    for a in sys.argv[1:]:
        if a.startswith("limit="):
            limit = int(a.split("=", 1)[1])
        if a.startswith("preset="):
            preset_name = a.split("=", 1)[1]
        if a == "--no-market":
            use_market = False
    if preset_name not in PRESETS:
        _log("unknown preset: " + preset_name)
        _log("available: " + str(list(PRESETS.keys())))
        return
    preset = PRESETS[preset_name]
    feat_keys = preset["features"]
    inter = preset["interactions"]
    total_d = len(feat_keys) + len(inter)
    _log("preset: " + preset_name + " features=" + str(len(feat_keys)) + " interactions=" + str(len(inter)) + " total_d=" + str(total_d))

    t0 = time.time()
    samples = load_data(limit=limit)
    _log("samples: " + str(len(samples)))
    matrices = build_matrix(samples, feat_keys, inter)
    samples = None  # メモリ解放
    _log("matrices: " + str(len(matrices)))

    train_set, test_set = split_train_test(matrices, "2025-01-01")
    matrices = None  # メモリ解放
    _log("train: " + str(len(train_set)) + " test: " + str(len(test_set)))
    _log("mode: " + ("market-based" if use_market else "feature-only"))

    w, loss_history = train(train_set, use_market=use_market, d=total_d)

    # baseline（市場のみ、w=0）
    train_market = eval_loss(np.zeros_like(w), train_set, use_market=True)
    test_market = eval_loss(np.zeros_like(w), test_set, use_market=True)
    # model（学習後）
    train_model = eval_loss(w, train_set, use_market=use_market)
    test_model = eval_loss(w, test_set, use_market=use_market)

    _log("=== 評価 ===")
    _log("  train: market-only=" + str(round(train_market, 4)) + " model=" + str(round(train_model, 4)) + " diff=" + str(round(train_model - train_market, 4)))
    _log("  test:  market-only=" + str(round(test_market, 4)) + " model=" + str(round(test_model, 4)) + " diff=" + str(round(test_model - test_market, 4)))

    model_id = "pl" if (use_market and preset_name == "all") else "pl_" + preset_name + ("" if use_market else "_nomarket")
    model_name = "plackett-luce-v6-" + preset_name + ("-market-based" if use_market else "-feature-only")
    save_feature_keys = list(feat_keys) + [x[0] for x in inter]
    save_params(w, STATS, loss_history, model_id=model_id, model_name=model_name, feature_keys=save_feature_keys)

    display_keys = list(feat_keys) + [x[0] for x in inter]
    order = sorted(zip(display_keys, w), key=lambda x: -abs(x[1]))
    _log("=== top weights ===")
    for k, v in order[:15]:
        _log("  " + k + ": " + str(round(v, 4)))
    _log("DONE " + str(round(time.time() - t0, 1)) + "s")


if __name__ == "__main__":
    main()
