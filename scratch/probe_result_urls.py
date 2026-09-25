"""結果・払戻URLの候補を実打して確定する。"""
import os
import re

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

date = "20230101"
track_cd = "43"
sponsor_cd = "43"
race_nb = 1

candidates = [
    ("RaceResult.do",       f"https://www.oddspark.com/keiba/RaceResult.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("RaceResult.do&type=1",f"https://www.oddspark.com/keiba/RaceResult.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}&type=1"),
    ("RaceResult.do&page=1",f"https://www.oddspark.com/keiba/RaceResult.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}&page=1"),
    ("Result.do",           f"https://www.oddspark.com/keiba/Result.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("RaceResult",          f"https://www.oddspark.com/keiba/RaceResult?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("Payback.do",          f"https://www.oddspark.com/keiba/Payback.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("Haraido.do",          f"https://www.oddspark.com/keiba/Haraido.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("OneDayRaceList.do",   f"https://www.oddspark.com/keiba/OneDayRaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}"),
    ("RaceList2.do",        f"https://www.oddspark.com/keiba/RaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}&mode=result"),
]

os.makedirs("debug_html", exist_ok=True)

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    for name, url in candidates:
        print(f"\n===== {name} =====")
        try:
            r = c.get(url)
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            title_txt = title.get_text(strip=True) if title else ""
            has_payout = ("払戻" in r.text) or ("払い戻し" in r.text) or ("的中" in r.text)
            has_finish = bool(re.search(r'着順|1着|2着|3着', r.text))
            has_horse = "馬名" in r.text
            print(f"  status={r.status_code} len={len(r.text)}")
            print(f"  title: {title_txt[:80]}")
            print(f"  払戻={has_payout} 着順={has_finish} 馬名={has_horse}")
            tclasses = [t.get("class") for t in soup.find_all("table")]
            print(f"  table classes: {tclasses[:8]}")
            if r.status_code == 200 and len(r.text) > 5000:
                fname = f"debug_html/probe_result_{re.sub(r'[^a-zA-Z0-9]', '_', name)}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"  saved: {fname}")
        except Exception as e:
            print(f"  ERROR: {e}")
