from backend.app.models.schemas import Race, Bet
import random
from backend.app.services.seeding import seed_for


def calc_ev(prob, odds):
    return prob * odds - 1.0


def mock_trifecta_odds(prob, race_id="", combo=""):
    rng = random.Random(seed_for(race_id + "|" + combo))
    return round(1.0 / max(prob, 0.001) * rng.uniform(1.1, 1.5), 1)


def kelly_fraction(prob, odds):
    denom = max(odds - 1.0, 1e-6)
    f = (prob * odds - 1.0) / denom
    return max(0.0, min(f, 1.0))


def suggest_amount(prob, odds, collateral, max_investment, fraction=0.25):
    f = kelly_fraction(prob, odds)
    raw = collateral * f * fraction
    capped = min(raw, max_investment)
    return int(capped // 100 * 100)


def build_bets(race, prediction, threshold_3rentan=0.12, min_prob=0.0, min_odds=0.0, collateral=100000, max_investment=10000):
    bets = []
    for tri in prediction.trifecta_probs:
        if tri.prob < min_prob:
            continue
        odds = mock_trifecta_odds(tri.prob, race.race_id, tri.combo)
        if odds < min_odds:
            continue
        ev = calc_ev(tri.prob, odds)
        if ev < threshold_rentan if False else ev < threshold_3rentan:
            continue
        amount = suggest_amount(tri.prob, odds, collateral, max_investment)
        bets.append(Bet(type="3連単", combination=tri.combo, amount=amount, ev=ev, prob=tri.prob, odds=odds))
    bets.sort(key=lambda x: x.ev or 0, reverse=True)
    return bets
