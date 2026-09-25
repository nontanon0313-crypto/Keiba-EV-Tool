"""9999.9 の扱いを確認。読み取り専用。"""
import time
import httpx

import backend.scraper.oddspark_keiba as ok
from backend.app.services.ev_calc import is_bettable_odds, ODDS_DISPLAY_MAX

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

print(f"ODDS_DISPLAY_MAX = {ODDS_DISPLAY_MAX}")
print(f"is_bettable_odds(9999.9)  = {is_bettable_odds(9999.9)}  (期待 False)")
print(f"is_bettable_odds(100.0)   = {is_bettable_odds(100.0)}   (期待 True)")
print(f"is_bettable_odds(1.0)     = {is_bettable_odds(1.0)}     (期待 False)")
print(f"is_bettable_odds(0.5)     = {is_bettable_odds(0.5)}     (期待 False)")

# 実ページで 3連単 (hn=4, 上限張付が多かった軸) を再パース
print("\n=== 実ページ検証: trifecta hn=4 ===")
date, track, sponsor, rn = "20230101", "43", "33", 1
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    url = (f"https://www.oddspark.com/keiba/Odds.do?sponsorCd={sponsor}&opTrackCd={track}"
           f"&raceDy={date}&raceNb={rn}&viewType=0&betType=8&horseNb=4&jikuNb=1")
    r = c.get(url)
    print(f"  status={r.status_code} len={len(r.text)}")
    parsed = ok.parse_trifecta(r.text)
    print(f"  parse_trifecta: {len(parsed)} 組 (期待 72)")
    n_9999 = sum(1 for v in parsed.values() if v.get("odds") == 9999.9)
    n_bettable = sum(1 for v in parsed.values() if is_bettable_odds(v.get("odds")))
    print(f"  9999.9 組数: {n_9999}")
    print(f"  投票対象組数: {n_bettable}")

    # 全軸合計
    print("\n=== 全軸合計 ===")
    merged = {}
    for hn in range(1, 11):
        url = (f"https://www.oddspark.com/keiba/Odds.do?sponsorCd={sponsor}&opTrackCd={track}"
               f"&raceDy={date}&raceNb={rn}&viewType=0&betType=8&horseNb={hn}&jikuNb=1")
        rr = c.get(url)
        if rr.status_code == 200:
            m = ok.parse_trifecta(rr.text)
            merged.update(m)
        time.sleep(0.8)
    print(f"  合計ユニーク: {len(merged)} / 720")
    n_9999_total = sum(1 for v in merged.values() if v.get("odds") == 9999.9)
    n_bettable_total = sum(1 for v in merged.values() if is_bettable_odds(v.get("odds")))
    print(f"  9999.9 組数: {n_9999_total}")
    print(f"  投票対象組数: {n_bettable_total}")

import os
os._exit(0)
