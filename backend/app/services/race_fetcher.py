"""レース取得。Turso の実レースのみ返す。Mock は完全削除済み。"""
from datetime import datetime
from backend.app.models.schemas import Race, Runner


def get_races():
    """Turso に保存された実レースを返す。なければ空リスト。
    JRA (12桁数字) と NAR (nar-*) の両方を含む。"""
    from backend.app.services import race_store

    items = race_store.list_races()
    out = []
    for it in items:
        p = it.get("payload") or {}
        runners = []
        for r in p.get("runners", []):
            try:
                runners.append(Runner(
                    horse_number=int(r.get("horse_number", 0)),
                    frame_number=int(r.get("frame_number", 0)),
                    horse_id=r.get("horse_id", ""),
                    horse_name=r.get("horse_name", ""),
                    jockey=r.get("jockey", ""),
                    trainer=r.get("trainer", ""),
                    weight=float(r.get("weight", 55.0) or 55.0),
                    horse_weight=r.get("horse_weight"),
                    horse_weight_change=r.get("horse_weight_change"),
                    odds_win=float(r.get("odds_win", 50.0) or 50.0),
                    popularity=r.get("popularity"),
                    status=r.get("status", "出走"),
                ))
            except (ValueError, TypeError):
                continue
        surf = p.get("surface") or "ダート"
        if surf not in ("芝", "ダート", "障害"):
            surf = "ダート"
        try:
            start_at = datetime.fromisoformat(p.get("start_at")) if p.get("start_at") else datetime.now()
        except (ValueError, TypeError):
            start_at = datetime.now()
        try:
            deadline_at = datetime.fromisoformat(p.get("deadline_at")) if p.get("deadline_at") else datetime.now()
        except (ValueError, TypeError):
            deadline_at = datetime.now()
        out.append(Race(
            race_id=it.get("race_id", ""),
            venue=p.get("venue", ""),
            date=p.get("date", ""),
            race_number=int(p.get("race_number", 0)),
            start_at=start_at,
            deadline_at=deadline_at,
            surface=surf,
            distance=int(p.get("distance", 0) or 0),
            runners=runners,
            odds_at=None,
            has_critical_change=False,
        ))
    return out


def get_real_races():
    """後方互換用エイリアス。"""
    return get_races()
