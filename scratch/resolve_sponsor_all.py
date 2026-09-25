"""全会場の正しい (track, sponsor) ペアを確定。"""
import time
import os
import re
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 2023年1月1日に開催があった track 一覧（DBから）
tracks = ["03", "06", "11", "12", "31", "32", "33", "34", "41", "42", "43", "51", "52", "55", "61"]

# 候補 sponsor: SPONSOR_TO_VENUEのキー + track自身
sponsor_candidates = ["03", "04", "06", "11", "13", "18", "20", "26", "29", "30", "33", "41", "43", "55", "61",
                      "12", "31", "32", "34", "42", "51", "52"]

os.makedirs("debug_html", exist_ok=True)
date = "20230101"

with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    for t in tracks:
        found = None
        for sp in sponsor_candidates:
            url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={date}&opTrackCd={t}&raceNb=1"
            try:
                r = c.get(url)
                if r.status_code == 200:
                    s = BeautifulSoup(r.text, "html.parser")
                    ttl = s.find("title")
                    tt = ttl.get_text(strip=True) if ttl else ""
                    m = re.search(r'】(.+?)競馬', tt)
                    venue = m.group(1) if m else "?"
                    found = (sp, venue)
                    print(f"  track={t} sponsor={sp}: OK → {venue}")
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if not found:
            print(f"  track={t}: 200なし")
        time.sleep(0.5)
