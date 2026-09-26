"""2023-01-01 の全会場を KaisaiRaceList.do から取得できるか確認。"""
import time
import re
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

date = "20230101"
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)

    print("=== KaisaiRaceList.do ===")
    r = c.get(f"https://www.oddspark.com/keiba/KaisaiRaceList.do?raceDy={date}")
    print(f"  status={r.status_code} len={len(r.text)}")
    soup = BeautifulSoup(r.text, "html.parser")
    # OneDayRaceList.do リンクを全抽出
    pairs = set()
    for m in re.finditer(r'OneDayRaceList\.do\?raceDy=(\d+)&(?:amp;)?opTrackCd=(\d+)&(?:amp;)?sponsorCd=(\d+)', r.text):
        pairs.add((m.group(2), m.group(3)))
    print(f"  リンクから抽出: {sorted(pairs)}")

    # track名も抽出
    venues = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "OneDayRaceList.do" in h:
            txt = a.get_text(strip=True)
            m = re.search(r'opTrackCd=(\d+)&(?:amp;)?sponsorCd=(\d+)', h)
            if m:
                venues.append((m.group(1), m.group(2), txt))
    print(f"  会場リンク:")
    for t, s, txt in sorted(set(venues)):
        print(f"    track={t} sponsor={s} ラベル='{txt}'")

    print("\n=== 現行 fetch_race_list_async と同じURL ===")
    r2 = c.get(f"https://www.oddspark.com/keiba/KaisaiRaceList.do?raceDy={date}")
    pattern = rf"OneDayRaceList\.do\?raceDy={date}&amp;opTrackCd=(\d+)&amp;sponsorCd=(\d+)"
    pairs2 = set()
    for m in re.finditer(pattern, r2.text):
        pairs2.add((m.group(1), m.group(2)))
    print(f"  現行パターン抽出: {sorted(pairs2)}")
