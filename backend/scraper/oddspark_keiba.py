"""オッズパーク地方競馬スクレイパー。

URL構造:
- 開催一覧: /keiba/KaisaiRaceList.do?raceDy=YYYYMMDD
- 1日出走表: /keiba/OneDayRaceList.do?raceDy=YYYYMMDD&opTrackCd=XX&sponsorCd=YY
- 出走表: /keiba/RaceList.do?raceDy=YYYYMMDD&opTrackCd=XX&sponsorCd=YY&raceNb=N
"""
from __future__ import annotations
import re
import time
import random
from typing import List, Dict, Optional

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.oddspark.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.oddspark.com/keiba/",
}

SPONSOR_TO_VENUE = {
    "06": "水沢",
    "13": "浦和",
    "20": "笠松",
    "26": "園田",
    "29": "高知",
    "55": "大井",
    "61": "川崎",
    "03": "船橋",
    "11": "門別",
    "41": "名古屋",
    "43": "金沢",
}


def _sleep():
    time.sleep(random.uniform(1.5, 2.5))


def fetch_race_list(date: str) -> List[Dict]:
    """指定日の地方競馬レース一覧を取得。"""
    url = f"{BASE}/keiba/KaisaiRaceList.do?raceDy={date}"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text

    soup = BeautifulSoup(html, "html.parser")
    venues = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].replace("&amp;", "&")
        m = re.search(r"raceDy=(\d+)&opTrackCd=(\d+)&sponsorCd=(\d+)", href)
        if not m:
            continue
        date_ = m.group(1)
        track_cd = m.group(2)
        sponsor_cd = m.group(3)

        if date_ != date:
            continue
        key = (track_cd, sponsor_cd)
        if key in seen:
            continue
        seen.add(key)
        venues.append({
            "track_cd": track_cd,
            "sponsor_cd": sponsor_cd,
            "venue": SPONSOR_TO_VENUE.get(sponsor_cd, ""),
            "date": date,
        })
    return venues


def fetch_one_day(track_cd: str, sponsor_cd: str, date: str) -> Optional[List[Dict]]:
    """1日出走表から全レース番号を取得。"""
    url = f"{BASE}/keiba/OneDayRaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")
    races = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"raceNb=(\d+)", href)
        if m:
            n = int(m.group(1))
            if n in seen:
                continue
            seen.add(n)
            races.append({
                "track_cd": track_cd,
                "sponsor_cd": sponsor_cd,
                "race_nb": n,
                "date": date,
            })
    return sorted(races, key=lambda x: x["race_nb"])


def fetch_shutuba(date: str, track_cd: str, sponsor_cd: str, race_nb: int) -> Optional[Dict]:
    """出走表と単勝オッズを取得。"""
    url = f"{BASE}/keiba/RaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    race_name = title_el.get_text(strip=True) if title_el else ""

    table = soup.select_one("table.ent1")
    if table is None:
        return None

    runners = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 8:
            continue
        try:
            frame = int(cells[0].get_text(strip=True))
            num = int(cells[2].get_text(strip=True))
        except (ValueError, IndexError):
            continue
        # 馬名は cells[5] 内の <a class="tx-midium"><strong>競走馬名</strong></a>
        horse_name = ""
        if len(cells) > 5:
            a_el = cells[5].select_one("a.tx-midium strong, a.tx-midium")
            if a_el:
                horse_name = a_el.get_text(strip=True)
            else:
                # フォールバック: 2番目の要素
                parts = [p.strip() for p in cells[5].get_text("\n", strip=True).split("\n") if p.strip()]
                horse_name = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
        jockey = cells[6].get_text(" ", strip=True) if len(cells) > 6 else ""
        odds_txt = cells[7].get_text(" ", strip=True) if len(cells) > 7 else ""
        m = re.search(r"([\d.]+)\s+(\d+)人気", odds_txt)
        odds_win = float(m.group(1)) if m else None
        popularity = int(m.group(2)) if m else None
        weight_txt = cells[8].get_text(strip=True) if len(cells) > 8 else ""
        m2 = re.search(r"(\d+)", weight_txt)
        horse_weight = int(m2.group(1)) if m2 else None

        runners.append({
            "horse_number": num,
            "frame_number": frame,
            "horse_name": horse_name,
            "jockey": jockey,
            "weight": None,
            "horse_weight": horse_weight,
            "odds_win": odds_win,
            "popularity": popularity,
        })
    return {
        "race_name": race_name,
        "track_cd": track_cd,
        "sponsor_cd": sponsor_cd,
        "race_nb": race_nb,
        "runners": runners,
    }


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else "20260923"
    venues = fetch_race_list(date)
    print(f"venues: {len(venues)}")
    for v in venues:
        print(f"  {v}")
        races = fetch_one_day(v["track_cd"], v["sponsor_cd"], date)
        print(f"    races: {len(races) if races else 0}")
        _sleep()
