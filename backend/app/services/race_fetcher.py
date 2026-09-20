from datetime import datetime, timedelta
from typing import List
from backend.app.models.schemas import Race, Runner
import random
class MockAdapter:
    def fetch_today_races(self) -> List[Race]:
        venues=["中山","阪神","東京"]; races=[]; now=datetime.now()
        for v in venues:
            for r in range(1,13):
                runners=[]
                for i in range(1,19):
                    runners.append(Runner(horse_number=i, frame_number=(i-1)//2+1, horse_id=f"{v}-{r}-{i}", horse_name=f"馬名{i}", jockey=f"騎手{i}", trainer=f"調教師{i}", weight=54.0+(i%4), horse_weight=450+random.randint(-10,10), horse_weight_change=random.randint(-4,4), odds_win=round(random.uniform(2.0,30.0),1), popularity=i, status="出走"))
                races.append(Race(race_id=f"{v}-{now.strftime('%Y%m%d')}-{r}", venue=v, date=now.strftime('%Y-%m-%d'), race_number=r, start_at=now+timedelta(hours=r), deadline_at=now+timedelta(hours=r, minutes=-2), surface="芝" if r%2==0 else "ダート", distance=1600 if r%2==0 else 1800, runners=runners, odds_at=now, has_critical_change=False))
        return races
adapter=MockAdapter()
def get_races():
    return adapter.fetch_today_races()
