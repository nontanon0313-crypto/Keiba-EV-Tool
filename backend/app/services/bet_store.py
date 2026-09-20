import json
from pathlib import Path
from datetime import datetime

STORE = Path("bets.json")


def _load():
    if not STORE.exists():
        return []
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(data):
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_bet(race_id, combo, amount, odds, prob=None, ev=None, ticket_type="trifecta"):
    data = _load()
    nid = (max([d.get("id", 0) for d in data]) + 1) if data else 1
    rec = {
        "id": nid,
        "race_id": race_id,
        "combo": combo,
        "amount": int(amount),
        "odds": float(odds),
        "prob": float(prob) if prob is not None else None,
        "ev": float(ev) if ev is not None else None,
        "ticket_type": ticket_type,
        "payout": None,
        "created_at": datetime.now().isoformat(),
    }
    data.append(rec)
    _save(data)
    return rec


def settle_bet(bet_id, payout):
    data = _load()
    for d in data:
        if d.get("id") == int(bet_id):
            d["payout"] = int(payout)
    _save(data)
    return {"settled": int(bet_id), "payout": int(payout)}


def _resolve(rec):
    payout = rec.get("payout")
    if payout is None:
        return ("pending", 0, 0)
    ret = int(payout)
    profit = ret - int(rec["amount"])
    status = "hit" if ret > 0 else "miss"
    return (status, ret, profit)


def list_bets():
    out = []
    for rec in _load():
        status, ret, profit = _resolve(rec)
        out.append(dict(rec, status=status, return_amount=ret, profit=profit))
    return out


def summary():
    rows = list_bets()
    stake = sum(r["amount"] for r in rows)
    ret = sum(r["return_amount"] for r in rows)
    profit = sum(r["profit"] for r in rows)
    hits = sum(1 for r in rows if r["status"] == "hit")
    settled = sum(1 for r in rows if r["status"] in ("hit", "miss"))
    expected_profit = sum((r["amount"] * r["ev"]) for r in rows if r.get("ev") is not None)
    probs = [r["prob"] for r in rows if r.get("prob") is not None]
    expected_hit_rate = (sum(probs) / len(probs)) if probs else 0.0
    expected_return = sum((r["amount"] * (1 + (r["ev"] or 0))) for r in rows if r.get("ev") is not None)
    odds_list = [r["odds"] for r in rows if r.get("odds") is not None]
    avg_odds = (sum(odds_list) / len(odds_list)) if odds_list else 0.0
    weighted_odds = (sum(r["amount"] * r["odds"] for r in rows if r.get("odds") is not None) / stake) if stake else 0.0
    return {
        "total_bets": len(rows),
        "total_stake": stake,
        "total_return": ret,
        "total_profit": profit,
        "roi": (profit / stake) if stake else 0.0,
        "hits": hits,
        "settled": settled,
        "hit_rate": (hits / settled) if settled else 0.0,
        "expected_hit_rate": expected_hit_rate,
        "expected_profit": expected_profit,
        "expected_return": expected_return,
        "expected_roi": (expected_profit / stake) if stake else 0.0,
        "avg_odds": avg_odds,
        "weighted_avg_odds": weighted_odds,
    }


def curve():
    rows = sorted(list_bets(), key=lambda r: r.get("created_at") or "")
    actual = [{"x": 0, "y": 0}]
    expected = [{"x": 0, "y": 0}]
    ax = 0
    ay = 0
    ex = 0
    ey = 0
    for r in rows:
        ax += r["amount"]
        ay += r["profit"]
        actual.append({"x": ax, "y": ay})
        ex += r["amount"]
        ey += r["amount"] * (r.get("ev") or 0)
        expected.append({"x": ex, "y": ey})
    return {"actual": actual, "expected": expected}


def delete_bet(bet_id):
    data = _load()
    data = [d for d in data if d.get("id") != int(bet_id)]
    _save(data)
    return {"deleted": int(bet_id)}
