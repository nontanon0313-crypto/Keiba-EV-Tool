"""netkeiba スクレイパー。

race_id 形式 (12桁): YYYY + 場コード(2) + 回(2) + 日(2) + R(2)
場コード: 01札幌 02函館 03福島 04新潟 05東京 06中山 07中京 08京都 09阪神 10小倉

結果テーブル: table.ResultsByRaceDetail
セル: 0着順 1枠番 2馬番 3馬名 4性齢 5斤量 6騎手 7タイム 16単勝 17人気
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


def parse_race_id(race_id: str) -> Dict:
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


def _to_float(txt):
    if not txt:
        return None
    t = txt.strip()
    if t in ("--", "", "**"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _to_int(txt):
    if not txt:
        return None
    t = txt.strip()
    if not t.isdigit():
        return None
    try:
        return int(t)
    except ValueError:
        return None


def fetch_race_result(race_id: str) -> Optional[Dict]:
    url = BASE_DB + "/race/" + race_id + "/"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")

    name_el = soup.select_one(".RaceName")
    race_name = name_el.get_text(strip=True) if name_el else ""

    surface = ""
    distance = 0
    info_text = ""
    for sel in [".RaceData01", ".RaceData", ".racedata"]:
        el = soup.select_one(sel)
        if el:
            info_text = el.get_text(" ", strip=True)
            break
    if info_text:
        m = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", info_text)
        if m:
            surface = {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(m.group(1), "")
            distance = int(m.group(2))

    table = soup.select_one("table.ResultsByRaceDetail")
    if table is None:
        return None
    rows = table.find_all("tr")
    runners = []
    finish_order = []
    for row in rows[1:]:
        tds = row.find_all("td")
        if len(tds) < 18:
            continue
        finish = _to_int(tds[0].get_text(strip=True))
        frame = _to_int(tds[1].get_text(strip=True))
        num = _to_int(tds[2].get_text(strip=True))
        if num is None:
            continue
        name_el = tds[3].find("a")
        horse_name = name_el.get_text(strip=True) if name_el else tds[3].get_text(strip=True)
        weight = _to_float(re.sub(r"[^\d.]", "", tds[5].get_text(strip=True)))
        jockey = tds[6].get_text(strip=True)
        odds_win = _to_float(tds[16].get_text(strip=True))
        popularity = _to_int(tds[17].get_text(strip=True))
        runners.append({
            "horse_number": num,
            "frame_number": frame or 0,
            "horse_name": horse_name,
            "jockey": jockey,
            "weight": weight or 0.0,
            "odds_win": odds_win,
            "popularity": popularity,
            "finish": finish,
        })
        if finish is not None and finish <= 3:
            finish_order.append((finish, num))
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


def fetch_race_card(race_id: str) -> Optional[Dict]:
    """発走前の出馬表 (枠・斤量・オッズ)。取れない場合 None。"""
    url = BASE_RACE + "/race/shutuba.html?race_id=" + race_id
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.Shutuba_Table")
    if table is None:
        return None
    runners = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 8:
            continue
        num = _to_int(tds[1].get_text(strip=True))
        if num is None:
            continue
        frame = _to_int(tds[0].get_text(strip=True)) or 0
        name_el = tds[3].find("a")
        name = name_el.get_text(strip=True) if name_el else tds[3].get_text(strip=True)
        jockey = tds[6].get_text(strip=True) if len(tds) > 6 else ""
        weight = _to_float(re.sub(r"[^\d.]", "", tds[5].get_text(strip=True) if len(tds) > 5 else ""))
        odds_win = None
        for td in tds:
            cls = " ".join(td.get("class", []))
            if "Txt_R" in cls or "Odds" in cls:
                v = _to_float(td.get_text(strip=True))
                if v is not None and odds_win is None:
                    odds_win = v
        runners.append({
            "horse_number": num,
            "frame_number": frame,
            "horse_name": name,
            "jockey": jockey,
            "weight": weight or 0.0,
            "odds_win": odds_win,
            "popularity": None,
        })
    return {"race_id": race_id, "runners": runners}


ODDS_TYPE_MAP = {
    "1": "win",
    "3": "quinella",
    "4": "exacta",
    "5": "wide",
    "6": "trio",
    "7": "trifecta",
}


def _combo_from_key(key, ticket):
    """APIのキー (例: 010203) を '1-2-3' 形式に変換。"""
    n = len(key) // 2
    parts = []
    for i in range(n):
        parts.append(str(int(key[i * 2: i * 2 + 2])))
    return "-".join(parts)


def _to_float_odds(s):
    if not s:
        return None
    t = str(s).replace(",", "").strip()
    try:
        v = float(t)
        if v <= 0:
            return None
        return v
    except ValueError:
        return None


def fetch_odds(race_id: str) -> Optional[Dict]:
    """内部APIから全券種オッズを取得。"""
    import json
    out = {}
    for t, ticket in ODDS_TYPE_MAP.items():
        url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
        params = {"race_id": race_id, "type": t, "action": "update", "sort": "1"}
        try:
            with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
                r = c.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            print("[odds]", ticket, "fail:", str(e)[:60])
            continue
        odds_map = (data.get("data") or {}).get("odds") or {}
        inner = odds_map.get(t) or {}
        result = {}
        for key, arr in inner.items():
            if not isinstance(arr, list) or not arr:
                continue
            combo = _combo_from_key(key, ticket)
            v = _to_float_odds(arr[0])
            if v is None:
                continue
            if ticket == "wide" and len(arr) >= 2:
                v2 = _to_float_odds(arr[1])
                result[combo] = {"min": v, "max": v2 or v}
            else:
                result[combo] = {"odds": v}
        out[ticket] = result
        _sleep()
    return out
