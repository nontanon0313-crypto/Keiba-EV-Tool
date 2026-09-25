"""出走表が非ログインで取れるか、候補URLを片っ端から実打して確認。
保存は debug_html/ 配下のみ。書き込みなし(Tursoには触らない)。
"""
import os
import re
from datetime import datetime

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
    ("RaceList.do", f"https://www.oddspark.com/keiba/RaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("Shutuba.do",  f"https://www.oddspark.com/keiba/Shutuba.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("RaceInfo.do", f"https://www.oddspark.com/keiba/RaceInfo.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("Odds.do",     f"https://www.oddspark.com/keiba/Odds.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
    ("RaceResult.do", f"https://www.oddspark.com/keiba/RaceResult.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
]

os.makedirs("debug_html", exist_ok=True)

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    for name, url in candidates:
        print(f"\n===== {name} =====")
        print(f"  url: {url}")
        try:
            r = c.get(url)
            print(f"  status={r.status_code} final_url={r.url} len={len(r.text)}")
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            title_txt = title.get_text(strip=True) if title else ""
            print(f"  title: {title_txt}")
            # 出走表らしさ判定
            has_ent1 = "ent1" in r.text
            has_horse = "horse" in r.text.lower()
            has_num = bool(re.search(r'raceNb=(\d+)', r.text))
            has_jockey = "騎手" in r.text
            has_馬名 = "馬名" in r.text
            print(f"  ent1={has_ent1} horse={has_horse} raceNb={has_num} 騎手={has_jockey} 馬名={has_馬名}")
            # table classes
            tclasses = [t.get("class") for t in soup.find_all("table")]
            print(f"  table classes: {tclasses[:8]}")
            # 既知の馬名
            for nm in ["フークサプライズ", "ハートマン", "スズカソブリン"]:
                if nm in r.text:
                    print(f"  馬名ヒット: {nm}")
            # 保存
            fname = f"debug_html/probe_{name.replace('.','_')}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  saved: {fname}")
        except Exception as e:
            print(f"  ERROR: {e}")
