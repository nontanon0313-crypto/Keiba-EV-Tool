"""netkeiba スクレイパー。

race_id 形式 (12桁): YYYY + 場コード(2) + 回(2) + 日(2) + R(2)
場コード: 01札幌 02函館 03福島 04新潟 05東京 06中山 07中京 08京都 09阪神 10小倉

礼儀: 1リクエストごとに1〜2秒の間隔、User-Agent 明示。
"""
from __future__ import annotations
import re
import time
import random
from typing import List, Dict, Optional

import httpx
from bs4 import BeautifulSoup


BASE_DB = "https://db.netkeiba.com"
BASE_RACE = "https://race.netkeiba.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36 KeibaEV/1.0"
}

VENUE_CODE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}


def _sleep():
    time.sleep(random.uniform(1.2, 2.2))


def parse_race_id(race_id: str) -> Dict[str, str]:
    race_id = str(race_id).strip()
    if len(race_id) != 12 or not race_id.isdigit():
        raise ValueError("race_id must be 12 digits: " + race_id)
    return {
        "race_id": race_id,
        "year": race_id[0:4],
        "venue_code": race_id[4:6],
        "venue": VENUE_CODE.get(race_id[4:6], ""),
        "kai": race_id[6:8],
        "day": race_id[8:10],
        "race_number": int(race_id[10:12]),
    }


def fetch_race_list(date: str) -> List[str]:
    url = BASE_RACE + "/top/race_list_sub.html?kaisai_date=" + date
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    ids = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"race_id=(\d{12})", a["href"])
        if m:
            ids.add(m.group(1))
    return sorted(ids)


def fetch_race_result(race_id: str) -> Optional[Dict]:
    url = BASE_DB + "/race/" + race_id + "/"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(".race_title")
    race_name = title_el.get_text(strip=True) if title_el else ""

    surface = ""
    distance = 0
    info = soup.select_one(".racedata dl")
    if info:
        info_text = info.get_text(" ", strip=True)
        m = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", info_text)
        if m:
            surface = {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(m.group(1), "")
            distance = int(m.group(2))

    table = soup.select_one("table.race_table_01")
    if table is None:
        return None
    rows = table.select("tr")[1:]
    runners = []
    finish_order = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 10:
            continue
        try:
            finish = tds[0].get_text(strip=True)
            finish_num = int(finish) if finish.isdigit() else None
        except Exception:
            finish_num = None
        frame_txt = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        num_txt = tds[3].get_text(strip=True) if len(tds) > 3 else ""
        name_el = tds[3].find("a") if len(tds) > 3 else None
        horse_name = name_el.get_text(strip=True) if name_el else tds[3].get_text(strip=True)
        try:
            horse_number = int(num_txt)
        except ValueError:
            continue
        try:
            frame = int(frame_txt) if frame_txt else 0
        except ValueError:
            frame = 0
        jockey_txt = tds[6].get_text(strip=True) if len(tds) > 6 else ""
        weight_txt = tds[5].get_text(strip=True) if len(tds) > 5 else ""
        try:
            weight = float(re.sub(r"[^\d.]", "", weight_txt) or 0)
        except ValueError:
            weight = 0.0
        odds_txt = tds[9].get_text(strip=True) if len(tds) > 9 else ""
        try:
            odds_win = float(odds_txt) if odds_txt and odds_txt != "--" else None
        except ValueError:
            odds_win = None
        popularity = None
        if len(tds) > 10:
            pop = tds[10].get_text(strip=True)
            try:
                popularity = int(pop) if pop.isdigit() else None
            except ValueError:
                popularity = None
        runners.append({
            "horse_number": horse_number,
            "frame_number": frame,
            "horse_name": horse_name,
            "jockey": jockey_txt,
            "weight": weight,
            "odds_win": odds_win,
            "popularity": popularity,
            "finish": finish_num,
        })
        if finish_num is not None and finish_num <= 3:
            finish_order.append((finish_num, horse_number))

    finish_order.sort()
    order = [hn for _, hn in finish_order]

    return {
        "race_id": race_id,
        "race_name": race_name,
        "surface": surface,
        "distance": distance,
        "runners": runners,
        "finish_order": order,
    }
