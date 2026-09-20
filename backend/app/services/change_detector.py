from backend.app.models.schemas import Race
def detect_critical_change(old: Race, new: Race) -> bool:
    if len(old.runners)!= len(new.runners):
        return True
    for o,n in zip(old.runners, new.runners):
        if o.status!= n.status:
            return True
        if o.jockey!= n.jockey:
            return True
        if o.horse_weight and n.horse_weight and abs(o.horse_weight - n.horse_weight) >= 10:
            return True
    return False
