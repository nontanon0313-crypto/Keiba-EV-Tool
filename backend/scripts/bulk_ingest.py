import os
"""指定日範囲のレース結果・オッズを一括取得。中断しても再開可能。"""
import sys
import atexit
import time
from datetime import datetime, timedelta

from backend.app.services import race_store, odds_store
from backend.app.services.scraper import netkeiba


def daterange(d0, d1):
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


atexit.register(lambda: os._exit(0))


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2024-06-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-06-02"
    sleep_sec = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5

    d0 = datetime.strptime(start, "%Y-%m-%d")
    d1 = datetime.strptime(end, "%Y-%m-%d")

    existing_races = {r["race_id"] for r in race_store.list_races()}
    existing_odds = {r["race_id"] for r in odds_store.list_odds()}
    print("existing races:", len(existing_races), "odds:", len(existing_odds), flush=True)

    for d in daterange(d0, d1):
        date_str = d.strftime("%Y%m%d")
        try:
            ids = netkeiba.fetch_race_list(date_str)
        except Exception as e:
            print("[{}] list fail: {}".format(date_str, str(e)[:80]), flush=True)
            continue
        todo = [rid for rid in ids if rid not in existing_races]
        print("[{}] {} races, {} todo".format(date_str, len(ids), len(todo)), flush=True)
        for i, rid in enumerate(todo):
            try:
                if rid not in existing_races:
                    data = netkeiba.fetch_race_result(rid)
                    if data and data.get("finish_order"):
                        race_store.save_race(rid, data)
                        existing_races.add(rid)
                    time.sleep(sleep_sec)
                # 既存オッズを確認して、足りない券種だけ追加取得
                cur = odds_store.get_odds(rid) or {}
                need = [t for t in ["win","place","quinella","wide","exacta","trio","trifecta"] if not cur.get(t)]
                if need:
                    o = netkeiba.fetch_odds(rid)
                    if o:
                        merged = dict(cur)
                        for k, v in o.items():
                            merged[k] = v
                        odds_store.save_odds(rid, merged)
                        existing_odds.add(rid)
                    time.sleep(sleep_sec)
                if (i + 1) % 3 == 0:
                    print("  [{}/{}] {} ok (races:{} odds:{})".format(i + 1, len(todo), rid, len(existing_races), len(existing_odds)), flush=True)
            except Exception as e:
                print("  [{}] {} fail: {}".format(date_str, rid, str(e)[:80]), flush=True)
                time.sleep(sleep_sec)
    print("ALL DONE", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
