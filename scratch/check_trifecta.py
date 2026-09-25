"""3連単の組数と軸馬別内訳を確認。読み取り専用。"""
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

date, track, sponsor, rn, N = "20230101", "43", "33", 1, 10

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)

    # 軸馬別に取得
    all_hn = {}
    for hn in range(1, N + 1):
        url = (f"https://www.oddspark.com/keiba/Odds.do?sponsorCd={sponsor}&opTrackCd={track}"
               f"&raceDy={date}&raceNb={rn}&viewType=0&betType=8"
               f"&horseNb={hn}&jikuNb=1")
        r = c.get(url)
        if r.status_code != 200:
            print(f"  hn={hn}: status={r.status_code}")
            continue
        parsed = ok.parse_trifecta(r.text)
        all_hn[hn] = parsed
        print(f"  hn={hn}: {len(parsed)} 組")
        time.sleep(1.0)

    # 合計ユニーク
    merged = {}
    for hn, m in all_hn.items():
        for k, v in m.items():
            merged[k] = v
    print(f"\n合計ユニーク: {len(merged)}")
    print(f"理論値（10頭）: 10*9*8 = 720")

    # サンプルキー
    keys = list(merged.keys())[:10]
    print(f"\nサンプルキー: {keys}")

    # 軸馬=1でどんなキーがあるか
    if 1 in all_hn:
        print(f"\nhn=1 のキー先頭20: {list(all_hn[1].keys())[:20]}")
