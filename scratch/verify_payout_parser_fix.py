"""修正後パーサーで実ページを再パースして payouts を確認。読み取り専用。"""
import os
import json
import time
from bs4 import BeautifulSoup
import httpx

import backend.scraper.oddspark_keiba as ok

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 検証対象（既に200が確認できているもの）
targets = [
    ("20230101", "43", "33", 1),   # 名古屋
    ("20230101", "43", "33", 10),
    ("20230101", "43", "33", 11),
    ("20230101", "55", "29", 1),   # 高知
    ("20230101", "51", "03", 1),   # 園田
]

os.makedirs("debug_html", exist_ok=True)
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    for d, t, sp, rn in targets:
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={d}&opTrackCd={t}&raceNb={rn}"
        r = c.get(url)
        print(f"\n===== nar-{d}-{t}-{rn} (status={r.status_code}) =====")
        if r.status_code != 200:
            print("  skip (not 200)")
            continue
        rid = f"nar-{d}-{t}-{rn}"
        parsed = ok.parse_result(r.text, rid)
        if not parsed:
            print("  parse_result -> None")
            continue
        po = parsed.get("payouts", {})
        for k in ["単勝", "複勝", "枠連", "枠単", "馬連", "馬単", "ワイド", "3連複", "3連単"]:
            if k in po:
                print(f"  {k}: {json.dumps(po[k], ensure_ascii=False)}")
            else:
                print(f"  {k}: (なし)")
        # 想定外キー
        extra = [k for k in po.keys() if k not in
                 ["単勝", "複勝", "枠連", "枠単", "馬連", "馬単", "ワイド", "3連複", "3連単"]]
        if extra:
            print(f"  [警告] 想定外キー: {extra}")
        time.sleep(1.5)
