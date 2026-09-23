from backend.app.models.schemas import Race, Runner
from backend.app.services.seeding import seed_for
from datetime import datetime, timedelta
import random


VENUES = ["中山", "阪神", "東京"]
SURFACES = ["芝", "ダート"]


class MockAdapter:
    def fetch_today_races(self):
        races = []
        base = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
        for v in VENUES:
            for r in range(1, 13):
                start = base + timedelta(minutes=30 * (r - 1) + 10)
                deadline = start - timedelta(minutes=2)
                rng = random.Random(seed_for(v + "-" + str(r) + "-race"))
                surface = rng.choice(SURFACES)
                distance = rng.choice([1200, 1400, 1600, 1800, 2000, 2400])
                runners = []
                for h in range(1, 19):
                    rrng = random.Random(seed_for(v + "-" + str(r) + "-" + str(h)))
                    odds = round(rrng.uniform(1.5, 99.9), 1)
                    runners.append(Runner(
                        horse_number=h,
                        frame_number=((h - 1) // 2) % 8 + 1,
                        horse_id=v + "-" + str(r) + "-" + str(h),
                        horse_name="馬名" + str(h),
                        jockey="騎手" + str(h),
                        trainer="調教師" + str(h),
                        weight=round(54.0 + (h % 4), 1),
                        horse_weight=440 + (h % 20),
                        horse_weight_change=rrng.randint(-6, 6),
                        odds_win=odds,
                        popularity=h,
                        status="出走",
                    ))
                races.append(Race(
                    race_id=v + "-" + datetime.now().strftime("%Y%m%d") + "-" + str(r),
                    venue=v,
                    date=datetime.now().strftime("%Y-%m-%d"),
                    race_number=r,
                    start_at=start,
                    deadline_at=deadline,
                    surface=surface,
                    distance=distance,
                    runners=runners,
                ))
        return races


class MockResultAdapter:
    """Mock 結果。race_id シードで 1〜3着 を返す。"""

    def fetch_result(self, race_id, num_runners=18):
        rng = random.Random(seed_for("result:" + race_id))
        nums = list(range(1, num_runners + 1))
        rng.shuffle(nums)
        return nums[:3]


_adapter = MockAdapter()
_result_adapter = MockResultAdapter()


def get_races():
    return _adapter.fetch_today_races()


def get_result(race_id, num_runners=18):
    return _result_adapter.fetch_result(race_id, num_runners)


def get_real_races():
    """Turso に保存された実レース（nar-*）を返す。"""
    from backend.app.services import race_store
    from backend.app.models.schemas import Race, Runner
    from datetime import datetime

    items = race_store.list_races()
    out = []
    for it in items:
        rid = it.get("race_id", "")
        if not rid.startswith("nar-"):
            continue
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
            race_id=rid,
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
