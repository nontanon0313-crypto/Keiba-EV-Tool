"""2023-01-01 に実際に開催があった会場を確定。"""
import time
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

date = "20230101"
# 全会場候補
candidates = [
    ("03", "03", "帯広"),
    ("06", "03", "門別"),
    ("11", "03", "盛岡"),
    ("12", "03", "水沢"),
    ("31", "03", "浦和"),
    ("32", "03", "船橋"),
    ("33", "03", "大井"),
    ("41", "03", "金沢"),
    ("42", "03", "笠松"),
    ("43", "33", "名古屋"),
    ("51", "03", "園田"),
    ("52", "03", "姫路"),
    ("55", "29", "高知"),
    ("61", "03", "佐賀"),
]

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    print(f"=== {date} の RaceResult 実在確認 ===")
    for track, sponsor, name in candidates:
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sponsor}&raceDy={date}&opTrackCd={track}&raceNb=1"
        try:
            r = c.get(url)
            s = BeautifulSoup(r.text, "html.parser")
            t = s.find("title")
            tt = t.get_text(strip=True) if t else ""
            has_table = "tb70" in r.text
            print(f"  {name}(track={track}): status={r.status_code} table={has_table} title={tt[:50]}")
        except Exception as e:
            print(f"  {name}: ERROR {e}")
        time.sleep(0.8)
