"""現行 fetch_shutuba で runners がどう取れるか確認。読み取り専用。"""
import backend.scraper.oddspark_keiba as ok

r = ok.fetch_shutuba("20230101", "43", "43", 1)
if not r:
    print("[NG] fetch_shutuba -> None")
else:
    print(f"race_name: {r.get('race_name')}")
    rs = r.get("runners", [])
    print(f"runners: {len(rs)}")
    for r0 in rs:
        print(f"  num={r0['horse_number']} frame={r0['frame_number']} "
              f"name={r0['horse_name'][:24]} odds={r0.get('odds_win')} pop={r0.get('popularity')}")

# 期待値（ent1 から読み取った実際の出走馬）
print()
print("期待: 1,2,3,4,5,6,7,8,9,10 の10頭")

import os
os._exit(0)
