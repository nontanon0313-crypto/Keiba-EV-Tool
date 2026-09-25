"""RaceResult.do を1リクエストずつ待機して再試行。
レート制限仮説の検証。Cookie/Referer/時間帯を切り分け。
"""
import time
import os
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": "https://www.oddspark.com/keiba/",
}

def probe(client, label, url, wait=0):
    if wait:
        time.sleep(wait)
    try:
        r = client.get(url, timeout=30)
        s = BeautifulSoup(r.text, "html.parser")
        t = s.find("title")
        tt = t.get_text(strip=True) if t else ""
        body = s.find("body")
        txt = body.get_text(" ", strip=True) if body else ""
        snippet = txt[:80]
        print(f"  [{label}] status={r.status_code} len={len(r.text)} title={tt[:40]}")
        print(f"      body: {snippet}")
        return r.status_code
    except Exception as e:
        print(f"  [{label}] ERROR: {e}")
        return None

os.makedirs("debug_html", exist_ok=True)

with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as c:
    # セッション確立
    print("=== セッション確立 ===")
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(2)

    # 同一URLを3秒間隔で3回
    print("\n=== 同一URL 3回試行 (wait 3s) ===")
    url = "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=43&raceDy=20230101&opTrackCd=43&raceNb=1"
    for i in range(3):
        probe(c, f"try{i+1}", url, wait=3 if i>0 else 0)

    # 別の過去日付（2024）
    print("\n=== 別の過去日付 ===")
    for d in ["20240922", "20250101"]:
        for sp in ["61", "43"]:
            u = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={d}&opTrackCd={sp}&raceNb=1"
            probe(c, f"{d}/{sp}", u, wait=3)

    # RaceList 経由で参照を積んでから RaceResult
    print("\n=== RaceList で参照積んでから RaceResult ===")
    c.get("https://www.oddspark.com/keiba/RaceList.do?raceDy=20230101&opTrackCd=43&sponsorCd=43&raceNb=1")
    time.sleep(3)
    probe(c, "after_racelist", url, wait=0)

    # 未来日付（レース無し）
    print("\n=== 未来日付(20260923, 51) ===")
    probe(c, "future", "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=51&raceDy=20260923&opTrackCd=51&raceNb=1", wait=3)

print("\n=== 完了 ===")
