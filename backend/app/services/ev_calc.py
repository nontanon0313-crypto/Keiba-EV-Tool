from backend.app.models.schemas import Bet
import random
from backend.app.services.seeding import seed_for


TICKET_TYPES = ("trifecta", "trio", "exacta", "quinella", "wide", "win", "place")

_TICKET_LABEL = {
    "trifecta": "3連単",
    "trio": "3連複",
    "exacta": "馬単",
    "quinella": "馬連",
    "wide": "ワイド",
    "win": "単勝",
    "place": "複勝",
}


def calc_ev(prob, odds):
    return prob * odds - 1.0


def mock_odds(prob, race_id="", combo="", ticket="trifecta"):
    rng = random.Random(seed_for(race_id + "|" + ticket + "|" + combo))
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


def _candidates(prediction, ticket_type):
    if ticket_type == "trifecta":
        return [(t.combo, t.prob) for t in prediction.trifecta_probs]
    if ticket_type == "win":
        return [(str(p.horse_number), p.win_prob) for p in prediction.probabilities]
    if ticket_type == "place":
        return [(str(p.horse_number), p.place_prob) for p in prediction.probabilities]
    from backend.app.services import derived
    if ticket_type == "trio":
        return [(x["combo"], x["prob"]) for x in derived.trio_probs(prediction.trifecta_probs)]
    if ticket_type == "exacta":
        return [(x["combo"], x["prob"]) for x in derived.exacta_probs(prediction.trifecta_probs)]
    if ticket_type == "quinella":
        return [(x["combo"], x["prob"]) for x in derived.quinella_probs(prediction.trifecta_probs)]
    if ticket_type == "wide":
        return [(x["combo"], x["prob"]) for x in derived.wide_probs(prediction.trifecta_probs)]
    return []


def build_bets(race, prediction, ticket_type="trifecta", threshold=None, min_prob=0.0, min_odds=0.0, collateral=100000, max_investment=10000):
    from backend.config import settings
    if threshold is None:
        threshold = {
            "trifecta": settings.EV_THRESHOLD_TRIFECTA,
            "trio": settings.EV_THRESHOLD_TRIO,
            "exacta": settings.EV_THRESHOLD_EXACTA,
            "quinella": settings.EV_THRESHOLD_EXACTA,
            "wide": settings.EV_THRESHOLD_WIDE,
            "win": 0.05,
            "place": 0.03,
        }.get(ticket_type, 0.12)
    bets = []
    for combo, prob in _candidates(prediction, ticket_type):
        if prob < min_prob:
            continue
        odds = mock_odds(prob, race.race_id, combo, ticket_type)
        if odds < min_odds:
            continue
        ev = calc_ev(prob, odds)
        if ev < threshold:
            continue
        amount = suggest_amount(prob, odds, collateral, max_investment)
        bets.append(Bet(type=_TICKET_LABEL.get(ticket_type, ticket_type), combination=combo, amount=amount, ev=ev, prob=prob, odds=odds))
    bets.sort(key=lambda x: x.ev or 0, reverse=True)
    return bets


def build_mixed_bets(race, prediction, tickets=None, ev_min=None, odds_min=None, top_n=None,
                     collateral=100000, max_investment=10000, bet_mode=None, bankroll=None):
    """複数券種を横断してEV順ソートし、上位N点を返す。
    bet_mode: fixed (固定額) / compound (資金の固定割合)"""
    from backend.config import settings
    if tickets is None:
        tickets = settings.MIXED_TICKETS
    if ev_min is None:
        ev_min = settings.MIXED_EV_MIN
    if odds_min is None:
        odds_min = settings.MIXED_ODDS_MIN
    if top_n is None:
        top_n = settings.MIXED_TOP_N
    if bet_mode is None:
        bet_mode = settings.BET_MODE
    candidates = []
    for t in tickets:
        for combo, prob in _candidates(prediction, t):
            if prob <= 0:
                continue
            odds = mock_odds(prob, race.race_id, combo, t)
            if odds < odds_min:
                continue
            ev = calc_ev(prob, odds)
            if ev < ev_min:
                continue
            candidates.append((ev, prob, odds, combo, t))
    candidates.sort(key=lambda x: x[0], reverse=True)
    picks = candidates[:top_n]
    if not picks:
        return []
    # 賭け金計算
    if bet_mode == "compound":
        if bankroll is None:
            bankroll = settings.BET_BANKROLL_INIT
        raw = bankroll * settings.BET_COMPOUND_RATIO
        # 払戻1000万円上限を考慮
        # 想定最大オッズ × 余裕係数 × 賭け金 <= PAYOUT_CAP
        cap_odds = settings.PAYOUT_CAP_MAX_ODDS * settings.PAYOUT_CAP_SAFETY
        cap_unit = settings.PAYOUT_CAP / cap_odds if cap_odds > 0 else raw
        unit = int(min(raw, cap_unit) // 100 * 100)
        if unit < 100:
            unit = 100
    else:
        unit = int(settings.BET_FIXED_UNIT // 100 * 100)
    bets = []
    for ev, prob, odds, combo, t in picks:
        bets.append(Bet(type=_TICKET_LABEL.get(t, t), combination=combo, amount=unit, ev=ev, prob=prob, odds=odds))
    return bets
