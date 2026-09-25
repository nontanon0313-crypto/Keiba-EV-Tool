"""園田(51)の結果ページ構造を確認。"""
import os
import time
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

url = "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=03&raceDy=20230101&opTrackCd=51&raceNb=1"
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    r = c.get(url)
    print(f"status={r.status_code} len={len(r.text)}")
    os.makedirs("debug_html", exist_ok=True)
    with open("debug_html/sonoda_result_51_1.html", "w", encoding="utf-8") as f:
        f.write(r.text)

soup = BeautifulSoup(r.text, "html.parser")
print(f"title: {soup.find('title').get_text(strip=True) if soup.find('title') else ''}")

print("\n=== table 全部 ===")
for i, tb in enumerate(soup.find_all("table")):
    txt = tb.get_text(" ", strip=True)
    print(f"  [{i}] class={tb.get('class')} rows={len(tb.find_all('tr'))} txt={txt[:120]}")

print("\n=== '着' '馬番' '馬名' を含むテーブル ===")
for i, tb in enumerate(soup.find_all("table")):
    txt = tb.get_text(" ", strip=True)
    if "馬名" in txt and "着" in txt:
        print(f"  [{i}] class={tb.get('class')}")
