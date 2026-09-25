"""RaceRefund の中身確認 + RaceResult 500 の原因切り分け。"""
import os
import re
from bs4 import BeautifulSoup
import httpx

HEADERS_DEFAULT = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/RaceList.do?raceDy=20230101&opTrackCd=43&sponsorCd=43&raceNb=1",
}

HEADERS_PC = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": "https://www.oddspark.com/keiba/RaceList.do?raceDy=20230101&opTrackCd=43&sponsorCd=43&raceNb=1",
}

print("===== 1) RaceRefund.do 中身 =====")
path = "debug_html/probe_correct_RaceRefund_venue.html"
with open(path, encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")
print(f"  title: {soup.find('title').get_text(strip=True) if soup.find('title') else ''}")
print(f"  tables: {len(soup.find_all('table'))}")
for i, tb in enumerate(soup.find_all("table")):
    cls = tb.get("class")
    txt = tb.get_text(" ", strip=True)
    print(f"  [{i}] class={cls} txt={txt[:200]}")

print("\n===== 2) RaceResult.do を複数条件で試す =====")
date = "20230101"
track_cd = "43"
sponsor_cd = "43"
race_nb = 1
base = f"https://www.oddspark.com/keiba/RaceResult.do"

trials = [
    ("default_headers", base + f"?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}", HEADERS_DEFAULT),
    ("pc_headers",      base + f"?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}", HEADERS_PC),
    ("no_referer",      base + f"?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}", {"User-Agent": HEADERS_DEFAULT["User-Agent"]}),
    ("with_result_extra", base + f"?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}&type=result", HEADERS_DEFAULT),
    ("alt_path_result", f"https://www.oddspark.com/keiba/result/RaceResult.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}", HEADERS_DEFAULT),
]

os.makedirs("debug_html", exist_ok=True)
for name, url, hdr in trials:
    print(f"\n  --- {name} ---")
    try:
        with httpx.Client(headers=hdr, timeout=25, follow_redirects=True) as c:
            r = c.get(url)
        print(f"    status={r.status_code} len={len(r.text)}")
        soup2 = BeautifulSoup(r.text, "html.parser")
        t = soup2.find("title")
        print(f"    title: {t.get_text(strip=True) if t else ''}")
        if r.status_code == 200 and len(r.text) > 5000:
            fname = f"debug_html/probe_more_{name}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"    saved: {fname}")
    except Exception as e:
        print(f"    ERROR: {e}")

print("\n===== 3) 過去の日付(2024/2026)でもRaceResult 500か =====")
for d in ["20240922", "20260923"]:
    url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=61&raceDy={d}&opTrackCd=61&raceNb=1"
    try:
        with httpx.Client(headers=HEADERS_DEFAULT, timeout=25, follow_redirects=True) as c:
            r = c.get(url)
        print(f"  {d}: status={r.status_code} len={len(r.text)}")
    except Exception as e:
        print(f"  {d}: ERROR {e}")
