from backend.app.models.schemas import Race, Bet
import random
def calc_ev(prob, odds):
    return prob*odds-1.0
def build_bets(race: Race, prediction, threshold_3rentan=0.12, budget=2000):
    bets=[]
    for tri in prediction.trifecta_probs:
        odds=round(1.0/max(tri.prob,0.001)*random.uniform(0.7,0.9),1)
        ev=calc_ev(tri.prob, odds)
        if ev>=threshold_3rentan:
            bets.append(Bet(type="3連単", combination=tri.combo, amount=0, ev=ev, prob=tri.prob, odds=odds))
    bets.sort(key=lambda x: x.ev or 0, reverse=True)
    bets=bets[:5]
    if not bets:
        return []
    total_ev=sum(b.ev for b in bets)
    for b in bets:
        b.amount=max(100, int(budget*(b.ev/total_ev)//100*100)) if total_ev>0 else budget//len(bets)
    return bets
