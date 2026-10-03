"""Plackett-Luce モデルを features テーブルから学習する。

スコア: score_i = exp(w · x_i)
レース内 softmax: P(i が1着) = exp(w·x_i) / Σ_j exp(w·x_j)
損失: -log P(winner) + λ ||w||^2
最適化: Adam

市場情報 (odds_win, popularity) は特徴に含めない。
これによりモデルは市場と独立に確率を推定する。

使い方:
    python3 -m backend.scripts.train_pl_model
"""
import os
import json
import time
import math
from datetime import datetime

import numpy as np
import libsql_client

LOG_PATH = "train_pl.log"

# 学習に使う特徴（この順でベクトル化）
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

# 学習時のスケーリングに使う統計
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
    """features テーブルから (race_id, [(num, feat_vec)], winner_num) を読み込む。"""
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        # レースごとに集める（race_id 単位で IN 句チャンク）
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

        # 勝者を取得（payload 全体を読まず、1着馬番のみ抽出）
        winners = {}
        last_rid = ""
        PAGE = 500
        while True:
            r2 = c.execute(
                "SELECT race_id, json_extract(payload, '$.finish_order[0]') FROM scraped_races "
                "WHERE race_id > ? ORDER BY race_id LIMIT ?",
                [last_rid, PAGE],
            )
            rows = list(r2.rows)
            if not rows:
                break
            for row in rows:
                rid = row[0]
                w = row[1]
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
            samples.append((rid, runners, w))
            if limit and len(samples) >= limit:
                break
        return samples
    finally:
        try:
            c.close()
        except Exception:
            pass


def build_matrix(samples):
    """各サンプルを (X_race (n×d), market_log (n), winner_idx) に変換。"""
    # 第一パス: 全値を集めて平均・標準偏差を計算
    all_vals = {k: [] for k in FEATURE_KEYS}
    for rid, runners, w in samples:
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
    _log("stats computed")

    # 第二パス: 実際の行列を作成
    out = []
    for rid, runners, w in samples:
        n = len(runners)
        X = np.zeros((n, len(FEATURE_KEYS)), dtype=np.float64)
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
            for j, k in enumerate(FEATURE_KEYS):
                v = _to_num(f.get(k))
                if v is None:
                    v = STATS[k][0]
                X[i, j] = (v - STATS[k][0]) / STATS[k][1]
            ow = _to_num(f.get("odds_win"))
            if ow and ow > 0 and inv_sum > 0:
                p_mkt = (1.0 / ow) / inv_sum
                market_log[i] = math.log(max(p_mkt, 1e-12))
            else:
                market_log[i] = math.log(1.0 / n) if n > 0 else -30.0
        if wi < 0:
            continue
        out.append((X, market_log, wi))
    return out


def train(matrices, epochs=200, lr=0.05, l2=1e-4):
    d = len(FEATURE_KEYS)
    w = np.zeros(d, dtype=np.float64)
    m = np.zeros(d, dtype=np.float64)
    v = np.zeros(d, dtype=np.float64)
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    t = 0
    n = len(matrices)
    loss_history = []
    _log("training start: n=" + str(n) + " d=" + str(d))
    # w=0 の損失を計算（市場確率そのまま）
    base_loss = 0.0
    for idx in range(n):
        X, market_log, wi = matrices[idx]
        sc = market_log.copy()
        sc -= sc.max()
        ex = np.exp(sc)
        p0 = ex / ex.sum()
        base_loss += -math.log(max(p0[wi], 1e-12))
    base_loss /= n
    _log("baseline (market only) loss=" + str(round(base_loss, 5)))
    for ep in range(epochs):
        perm = np.random.permutation(n)
        total_loss = 0.0
        for idx in perm:
            X, market_log, wi = matrices[idx]
            scores = X @ w
            scores -= scores.max()
            exp_s = np.exp(scores)
            ssum = exp_s.sum()
            P = exp_s / ssum
            total_loss += -math.log(max(P[wi], 1e-12))
            # 勾配: Σ P_i X_i - X_wi + 2λ w
            grad = P @ X - X[wi] + 2 * l2 * w
            # Adam
            t += 1
            m = beta1 * m + (1 - beta1) * grad
            v = beta2 * v + (1 - beta2) * (grad * grad)
            m_hat = m / (1 - beta1 ** t)
            v_hat = v / (1 - beta2 ** t)
            w -= lr * m_hat / (np.sqrt(v_hat) + eps)
        avg_loss = total_loss / n
        loss_history.append(round(avg_loss, 5))
        _log("epoch " + str(ep + 1) + "/" + str(epochs) + " loss=" + str(round(avg_loss, 5)))
    return w, loss_history


def save_params(w, stats, loss_history=None):
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
            "model": "plackett-luce-v5",
            "feature_keys": FEATURE_KEYS,
            "weights": w.tolist(),
            "stats": {k: list(v) for k, v in stats.items()},
            "trained_at": datetime.now().isoformat(),
            "loss_history": loss_history or [],
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO model_params (id, payload, updated_at) VALUES ('pl', ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
            [pj, datetime.now().isoformat()],
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
    for a in sys.argv[1:]:
        if a.startswith("limit="):
            limit = int(a.split("=", 1)[1])
    t0 = time.time()
    samples = load_data(limit=limit)
    _log("samples: " + str(len(samples)))
    matrices = build_matrix(samples)
    _log("matrices: " + str(len(matrices)))
    w, loss_history = train(matrices)
    save_params(w, STATS, loss_history)
    # 重みの確認
    order = sorted(zip(FEATURE_KEYS, w), key=lambda x: -abs(x[1]))
    _log("=== top weights ===")
    for k, v in order[:15]:
        _log("  " + k + ": " + str(round(v, 4)))
    _log("DONE " + str(round(time.time() - t0, 1)) + "s")


if __name__ == "__main__":
    main()
import os as _o
_o._exit(0)
