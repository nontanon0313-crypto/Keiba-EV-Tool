"""2023年の複数日付・trackでRaceResult.doの成功条件を確定。"""
import time
import os
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 2023年の様々な日付 x track
targets = [
    ("20230101", "43"),
    ("20230102", "43"),
    ("20230105", "43"),
    ("20230301", "43"),
    ("20230601", "43"),
    ("20230625", "43"),
    ("20230101", "42"),
    ("20230101", "51"),
    ("20230101", "55"),
    ("20230101", "61"),
    ("20230601", "51"),
    ("20230625", "55"),
]

os.makedirs("debug_html", exist_ok=True)
results = []

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    for d, t in targets:
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={t}&raceDy={d}&opTrackCd={t}&raceNb=1"
        try:
            r = c.get(url)
            s = BeautifulSoup(r.text, "html.parser")
            ttl = s.find("title")
            tt = ttl.get_text(strip=True) if ttl else ""
            results.append((d, t, r.status_code, tt[:60]))
            print(f"  {d}/{t}: {r.status_code} {tt[:60]}")
            if r.status_code == 200 and len(r.text) > 15000:
                fname = f"debug_html/result_ok_{d}_{t}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"    saved: {fname}")
        except Exception as e:
            print(f"  {d}/{t}: ERROR {e}")
        time.sleep(2)

print("\n=== 成功のみ ===")
for d, t, s, tt in results:
    if s == 200:
        print(f"  {d}/{t}: {tt}")
