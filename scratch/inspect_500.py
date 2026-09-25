"""RaceResult.do の500応答の中身を確認。"""
import os
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

urls = [
    ("past_500", "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=43&raceDy=20230101&opTrackCd=43&raceNb=1"),
    ("future_200", "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=51&raceDy=20260923&opTrackCd=51&raceNb=1"),
]

os.makedirs("debug_html", exist_ok=True)
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    for name, url in urls:
        print(f"\n===== {name} =====")
        print(f"  url: {url}")
        r = c.get(url)
        print(f"  status={r.status_code} len={len(r.text)}")
        print(f"  server={r.headers.get('server')} content-type={r.headers.get('content-type')}")
        fname = f"debug_html/result_{name}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"  saved: {fname}")
        soup = BeautifulSoup(r.text, "html.parser")
        body = soup.find("body")
        txt = body.get_text("\n", strip=True) if body else soup.get_text("\n", strip=True)
        print(f"  --- body text ({len(txt)}文字) ---")
        print(txt[:1500])
