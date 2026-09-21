from backend.app.models.schemas import Race, Prediction, Probability, TrifectaProb
from backend.app.services.seeding import seed_for
from datetime import datetime
import random


def plackett_luce_win_probs(race):
    scores = []
    for runner in race.runners:
        inv_odds = 1.0 / (runner.odds_win or 10.0)
        weight_penalty = (runner.weight - 54.0) * 0.02
        score = inv_odds - weight_penalty
        scores.append((runner.horse_number, max(score, 0.001)))
    total = sum(s for _, s in scores)
    probs = []
    for hn, s in scores:
        wp = s / total
        pp = min(wp * 2.8, 0.95)
        probs.append(Probability(horse_number=hn, win_prob=wp, place_prob=pp))
    probs.sort(key=lambda x: x.win_prob, reverse=True)
    return probs


def trifecta_probs(race, win_probs):
    score_map = {p.horse_number: p.win_prob for p in win_probs}
    nums = [r.horse_number for r in race.runners[:8]]
    out = []
    for a in nums:
        for b in nums:
            if b == a:
                continue
            for c in nums:
                if c in (a, b):
                    continue
                p_a = score_map[a]
                rem = sum(score_map[x] for x in nums if x != a)
                if rem <= 0:
                    continue
                p_b = score_map[b] / rem
                rem2 = sum(score_map[x] for x in nums if x not in (a, b))
                if rem2 <= 0:
                    continue
                p_c = score_map[c] / rem2
                prob = p_a * p_b * p_c
                combo = str(a) + "-" + str(b) + "-" + str(c)
                out.append(TrifectaProb(combo=combo, prob=prob))
    out.sort(key=lambda x: x.prob, reverse=True)
    return out[:30]


def predict_race(race):
    random.seed(seed_for(race.race_id))
    win_probs = plackett_luce_win_probs(race)
    tri = trifecta_probs(race, win_probs)
    return Prediction(race_id=race.race_id, created_at=datetime.now(), probabilities=win_probs, trifecta_probs=tri, model_version="plackett-luce-v2-noNoise")
