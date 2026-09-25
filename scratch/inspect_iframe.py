"""RaceRefund.do の iframe src と、raceNb 付き候補URLを実打。"""
import os
import re
from bs4 import BeautifulSoup
import httpx

path = "debug_html/probe_correct_RaceRefund_venue.html"
with open(path, encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")

print("=== iframe src ===")
for i, ifr in enumerate(soup.find_all("iframe")):
    print(f"  iframe[{i}] src={ifr.get('src')} id={ifr.get('id')} name={ifr.get('name')}")

print("\n=== select / option ===")
for i, sel in enumerate(soup.find_all("select")):
    print(f"  select[{i}] id={sel.get('id')} name={sel.get('name')}")
    for opt in sel.find_all("option"):
        print(f"    option value={opt.get('value')} txt={opt.get_text(strip=True)}")

print("\n=== 01R リンク href（重複除去） ===")
seen = set()
for a in soup.find_all("a", href=True):
    h = a["href"]
    if "RaceRefund" in h or "Refund" in h or "RaceResult" in h:
        if h not in seen:
            seen.add(h)
            print(f"  txt='{a.get_text(strip=True)}' href={h}")

print("\n=== 'iframe' を含む script ===")
for i, sc in enumerate(soup.find_all("script")):
    s = sc.string or ""
    if "iframe" in s.lower() or "frame" in s.lower():
        print(f"  script[{i}]: {s[:300]}")

# raceNb付き候補を実打
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/RaceRefund.do?sponsorCd=43&raceDy=20230101&opTrackCd=43",
}
print("\n=== raceNb 付き候補 ===")
candidates = [
    ("RaceRefund+raceNb", "https://www.oddspark.com/keiba/RaceRefund.do?sponsorCd=43&raceDy=20230101&opTrackCd=43&raceNb=1"),
    ("RaceRefund+raceNo", "https://www.oddspark.com/keiba/RaceRefund.do?sponsorCd=43&raceDy=20230101&opTrackCd=43&raceNo=1"),
    ("RaceRefund+dispType", "https://www.oddspark.com/keiba/RaceRefund.do?sponsorCd=43&raceDy=20230101&opTrackCd=43&dispType=1"),
]
with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
    for name, url in candidates:
        try:
            r = c.get(url)
            s2 = BeautifulSoup(r.text, "html.parser")
            iframes = s2.find_all("iframe")
            tables = s2.find_all("table")
            t = s2.find("title")
            print(f"  {name}: status={r.status_code} len={len(r.text)} iframe={len(iframes)} table={len(tables)} title={t.get_text(strip=True) if t else ''}")
            for i, ifr in enumerate(iframes):
                print(f"    iframe[{i}] src={ifr.get('src')}")
            if r.status_code == 200 and len(r.text) > 10000:
                fname = f"debug_html/probe_refund_{re.sub(r'[^a-zA-Z0-9]', '_', name)}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"    saved: {fname}")
        except Exception as e:
            print(f"  {name}: ERROR {e}")
