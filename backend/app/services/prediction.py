"""Plackett-Luce 順位モデルによる予想。

現状の実装: 市場オッズから1着確率を算出する。
これは「市場の写し」であり、独自予想モデルへの置き換えは別タスク。

データ品質ルール (RULES.md):
- odds_win is None は除外
- odds_win == 50.0 (旧パーサ取得失敗痕跡) は除外
- odds_win <= 1.0 は除外
"""
from backend.app.models.schemas import Race, Prediction, Probability, TrifectaProb
from backend.constants import ODDS_MISSING_LEGACY
from datetime import datetime


def _is_valid_odds(odds):
    if odds is None:
        return False
    try:
        v = float(odds)
    except (ValueError, TypeError):
        return False
    if v <= 1.0:
        return False
    if v == ODDS_MISSING_LEGACY:
        return False
    return True


def _place_prob_exact(target_hn, p_norm):
    """Plackett-Luce モデルで3着以内確率を正確に計算する。

    P(target が3着以内) = P(1着) + P(2着) + P(3着)
    p_norm: {horse_number: win_prob} 正規化済み
    """
    pt = p_norm.get(target_hn, 0.0)
    if pt <= 0:
        return 0.0
    # P(2着) = Σ_{j≠t} p_j * pt / (1 - p_j)
    p2 = 0.0
    for j, pj in p_norm.items():
        if j == target_hn:
            continue
        denom = 1.0 - pj
        if denom <= 1e-12:
            continue
        p2 += pj * pt / denom
    # P(3着) = Σ_{j≠t} Σ_{k≠t,j} p_j * p_k/(1-p_j) * pt/(1-p_j-p_k)
    p3 = 0.0
    for j, pj in p_norm.items():
        if j == target_hn:
            continue
        d1 = 1.0 - pj
        if d1 <= 1e-12:
            continue
        for k, pk in p_norm.items():
            if k == target_hn or k == j:
                continue
            d2 = 1.0 - pj - pk
            if d2 <= 1e-12:
                continue
            p3 += pj * pk / d1 * pt / d2
    return pt + p2 + p3


def plackett_luce_win_probs(race):
    """市場オッズから Plackett-Luce スコアを構築し、1着確率を算出する。

    注意: 現状はスコア = 1 / odds_win であり、市場確率の写し。
    独自モデルへの置き換えは別タスク。
    """
    valid = []
    for runner in race.runners:
        if not _is_valid_odds(runner.odds_win):
            continue
        valid.append((runner.horse_number, 1.0 / float(runner.odds_win)))
    if not valid:
        return []
    total = sum(s for _, s in valid)
    if total <= 0:
        return []
    p_norm = {hn: s / total for hn, s in valid}
    probs = []
    for hn in p_norm:
        wp = p_norm[hn]
        pp = _place_prob_exact(hn, p_norm)
        probs.append(Probability(horse_number=hn, win_prob=wp, place_prob=pp))
    probs.sort(key=lambda x: x.win_prob, reverse=True)
    return probs


def trifecta_probs(race, win_probs):
    score_map = {p.horse_number: p.win_prob for p in win_probs}
    nums = [r.horse_number for r in race.runners if r.horse_number in score_map]
    out = []
    for a in nums:
        pa = score_map[a]
        rem_a = sum(score_map[x] for x in nums if x != a)
        if rem_a <= 0:
            continue
        for b in nums:
            if b == a:
                continue
            pb = score_map[b] / rem_a
            rem_b = sum(score_map[x] for x in nums if x not in (a, b))
            if rem_b <= 0:
                continue
            for c in nums:
                if c in (a, b):
                    continue
                pc = score_map[c] / rem_b
                prob = pa * pb * pc
                combo = str(a) + "-" + str(b) + "-" + str(c)
                out.append(TrifectaProb(combo=combo, prob=prob))
    out.sort(key=lambda x: x.prob, reverse=True)
    return out


def predict_race(race):
    win_probs = plackett_luce_win_probs(race)
    tri = trifecta_probs(race, win_probs)
    return Prediction(
        race_id=race.race_id,
        created_at=datetime.now(),
        probabilities=win_probs,
        trifecta_probs=tri,
        model_version="plackett-luce-v5-market-based",
    )
