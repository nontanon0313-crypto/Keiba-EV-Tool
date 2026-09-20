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
