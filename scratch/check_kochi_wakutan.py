"""高知(55)の枠単が本当に発売なしなのか確認。読み取り専用。"""
import os
import time
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

date = "20230101"
track = "55"
sponsor = "29"

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sponsor}&raceDy={date}&opTrackCd={track}&raceNb=1"
    r = c.get(url)
    print(f"status={r.status_code} len={len(r.text)}")
    os.makedirs("debug_html", exist_ok=True)
    with open("debug_html/kochi_result_55_1.html", "w", encoding="utf-8") as f:
        f.write(r.text)

soup = BeautifulSoup(r.text, "html.parser")
print(f"title: {soup.find('title').get_text(strip=True) if soup.find('title') else ''}")

print("\n=== minipay テーブル ===")
for ti, tbl in enumerate(soup.select("table.minipay")):
    print(f"\n--- minipay[{ti}] ---")
    for ri, row in enumerate(tbl.find_all("tr")):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        texts = [c.get_text(" ", strip=True)[:24] for c in cells]
        spans = [(c.get("rowspan"), c.get("colspan")) for c in cells]
        print(f"  row{ri}: texts={texts}")
        print(f"          spans={spans}")

# 枠単・枠連の記載を探す
print("\n=== '枠単' '枠連' の出現 ===")
body = soup.get_text(" ", strip=True)
for kw in ["枠単", "枠連"]:
    idx = body.find(kw)
    if idx >= 0:
        print(f"  '{kw}': ...{body[max(0,idx-20):idx+120]}...")
    else:
        print(f"  '{kw}': 見つからない")
