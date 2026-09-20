from datetime import datetime
from backend.app.services.storage import get_storage


def _load():
    return get_storage().load_all()


def _save(data):
    get_storage().save_all(data)


def add_bet(race_id, combo, amount, odds, prob=None, ev=None, ticket_type="trifecta", model_version=None):
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
        "model_version": model_version,
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
    ax = ay = ex = ey = 0
    for r in rows:
        ax += r["amount"]; ay += r["profit"]; actual.append({"x": ax, "y": ay})
        ex += r["amount"]; ey += r["amount"] * (r.get("ev") or 0); expected.append({"x": ex, "y": ey})
    return {"actual": actual, "expected": expected}


def delete_bet(bet_id):
    data = [d for d in _load() if d.get("id") != int(bet_id)]
    _save(data)
    return {"deleted": int(bet_id)}


def replace_all(items):
    clean = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        clean.append({
            "id": int(it.get("id", 0)),
            "race_id": str(it.get("race_id", "")),
            "combo": str(it.get("combo", "")),
            "amount": int(it.get("amount", 0)),
            "odds": float(it.get("odds", 0.0)),
            "prob": float(it["prob"]) if it.get("prob") is not None else None,
            "ev": float(it["ev"]) if it.get("ev") is not None else None,
            "ticket_type": str(it.get("ticket_type", "trifecta")),
            "model_version": it.get("model_version"),
            "payout": int(it["payout"]) if it.get("payout") is not None else None,
            "created_at": str(it.get("created_at", "")),
        })
    seen = set()
    for c in clean:
        if c["id"] in seen or c["id"] <= 0:
            c["id"] = (max(seen) + 1) if seen else 1
        seen.add(c["id"])
    _save(clean)
    return {"imported": len(clean)}
