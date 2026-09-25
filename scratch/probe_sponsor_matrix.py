"""sponsor_cd の正しい値を確定。track=43名古屋で sponsor を変えて試行。"""
import time
import os
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 名古屋=track43, sponsor を候補で試す
targets = [
    ("20230101", "43", "33"),  # raceRefund select にあった値
    ("20230101", "43", "43"),
    ("20230101", "43", "18"),  # SPONSOR_TO_VENUE に名古屋として登録あり
    ("20230101", "43", "41"),  # SPONSOR_TO_VENUE に名古屋として登録あり
    ("20230301", "43", "33"),
    ("20230601", "43", "33"),
    # 他場も
    ("20230101", "42", "20"),  # 笠松
    ("20230101", "42", "42"),
    ("20230101", "51", "55"),  # 園田
    ("20230101", "51", "51"),
]

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    for d, t, sp in targets:
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={d}&opTrackCd={t}&raceNb=1"
        try:
            r = c.get(url)
            s = BeautifulSoup(r.text, "html.parser")
            ttl = s.find("title")
            tt = ttl.get_text(strip=True) if ttl else ""
            print(f"  d={d} track={t} sponsor={sp}: {r.status_code} {tt[:70]}")
        except Exception as e:
            print(f"  d={d} track={t} sponsor={sp}: ERROR {e}")
        time.sleep(1.5)
