"""正しいパラメータ順序で結果・払戻URLを実打確認。"""
import os
import re
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/RaceList.do?raceDy=20230101&opTrackCd=43&sponsorCd=43&raceNb=1",
}

date = "20230101"
track_cd = "43"
sponsor_cd = "43"
race_nb = 1

candidates = [
    ("RaceResult_sponsor_first", f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}"),
    ("RaceResult_track_first",   f"https://www.oddspark.com/keiba/RaceResult.do?opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceDy={date}&raceNb={race_nb}"),
    ("RaceRefund_venue",         f"https://www.oddspark.com/keiba/RaceRefund.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}"),
]

os.makedirs("debug_html", exist_ok=True)

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    for name, url in candidates:
        print(f"\n===== {name} =====")
        print(f"  url: {url}")
        try:
            r = c.get(url)
            soup = BeautifulSoup(r.text, "html.parser")
            t = soup.find("title")
            title = t.get_text(strip=True) if t else ""
            print(f"  status={r.status_code} len={len(r.text)}")
            print(f"  title: {title}")
            has_payout = "払戻" in r.text or "払い戻し" in r.text
            has_finish = bool(re.search(r'1着|2着|3着|着順', r.text))
            has_馬名 = "馬名" in r.text or "フークサプライズ" in r.text
            print(f"  払戻={has_payout} 着順={has_finish} 馬名={has_馬名}")
            tclasses = [tb.get("class") for tb in soup.find_all("table")]
            print(f"  table classes: {tclasses[:10]}")
            if r.status_code == 200:
                fname = f"debug_html/probe_correct_{name}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"  saved: {fname}")
        except Exception as e:
            print(f"  ERROR: {e}")
