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
    time.sleep(random.uniform(0.2, 0.4))


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


def fetch_one_day_detail(track_cd: str, sponsor_cd: str, date: str) -> List[Dict]:
    """1日出走表から各レースの発走時刻・距離・馬場を取得。"""
    url = f"{BASE}/keiba/OneDayRaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"raceNb=(\d+)", href)
        if not m:
            continue
        rn = int(m.group(1))
        if rn in seen:
            continue
        parent = a.find_parent(["tr", "li", "div"])
        if not parent:
            continue
        txt = parent.get_text(" ", strip=True)
        t = re.search(r"(\d{1,2}):(\d{2})", txt)
        start_hhmm = t.group(0) if t else None
        # 距離
        dist_m = re.search(r"(\d{3,4})m", txt)
        distance = int(dist_m.group(1)) if dist_m else 0
        # 馬場
        surface = "ダート"
        if "芝" in txt:
            surface = "芝"
        elif "障" in txt:
            surface = "障害"
        seen.add(rn)
        out.append({
            "race_nb": rn,
            "start_hhmm": start_hhmm,
            "distance": distance,
            "surface": surface,
        })
    return sorted(out, key=lambda x: x["race_nb"])


# ============================================================
# 全券種オッズ取得 (betType は oddspark 実データで確認済み)
# 1=単勝/複勝, 5=馬単, 6=馬連, 7=ワイド, 8=3連単, 9=3連複
# ============================================================

BET_TYPE = {
    "win": "1",       # 単勝/複勝
    "exacta": "5",    # 馬単
    "quinella": "6",  # 馬連
    "wide": "7",      # ワイド
    "trifecta": "8",  # 3連単
    "trio": "9",      # 3連複
}


def _parse_float(txt):
    """'161.3' や '1,234.5' を float に。'9999.9' は上限として None。"""
    if not txt:
        return None
    t = str(txt).replace(",", "").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    if v >= 9999.9:
        return None
    return v


def _parse_range(txt):
    """'4.2-12.5' を (min, max) に。"""
    if not txt:
        return None, None
    m = re.match(r"([\d.]+)\s*-\s*([\d.]+)", str(txt))
    if not m:
        v = _parse_float(txt)
        return v, v
    return _parse_float(m.group(1)), _parse_float(m.group(2))


def fetch_odds_single_type(date, track_cd, sponsor_cd, race_nb, bet_type, client=None):
    """1券種のオッズページを取得してHTMLを返す。"""
    url = f"{BASE}/keiba/Odds.do?sponsorCd={sponsor_cd}&opTrackCd={track_cd}&raceDy={date}&raceNb={race_nb}&viewType=0&betType={bet_type}"
    if client is None:
        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    r = client.get(url)
    r.raise_for_status()
    return r.text


def parse_quinella(html):
    """馬連 (bt6) パース。
    row index (1〜) = 1着馬番号
    各セルペア: <th>2着馬番号</th><td>オッズ</td>"""
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.select_one("table.tb73")
    if not tbl:
        return {}
    out = {}
    rows = tbl.find_all("tr")
    for row_idx, row in enumerate(rows[1:], start=1):
        cells = row.find_all(["td", "th"])
        a = row_idx  # 1着馬
        for i in range(0, len(cells) - 1, 2):
            try:
                b = int(cells[i].get_text(strip=True))
            except ValueError:
                continue
            odds = _parse_float(cells[i+1].get_text(strip=True))
            if odds is None:
                continue
            key = "-".join(sorted([str(a), str(b)], key=lambda x: int(x)))
            out[key] = {"odds": odds}
    return out


def parse_wide(html):
    """ワイド (bt7) パース。馬連と同じ構造、値は範囲。"""
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.select_one("table.tb73")
    if not tbl:
        return {}
    out = {}
    rows = tbl.find_all("tr")
    for row_idx, row in enumerate(rows[1:], start=1):
        cells = row.find_all(["td", "th"])
        a = row_idx
        for i in range(0, len(cells) - 1, 2):
            try:
                b = int(cells[i].get_text(strip=True))
            except ValueError:
                continue
            lo, hi = _parse_range(cells[i+1].get_text(strip=True))
            if lo is None:
                continue
            key = "-".join(sorted([str(a), str(b)], key=lambda x: int(x)))
            out[key] = {"min": lo, "max": hi if hi is not None else lo}
    return out


def fetch_odds_all(date, track_cd, sponsor_cd, race_nb):
    """全券種オッズを取得。
    Returns: {"quinella": {...}, "wide": {...}, ...}
    """
    result = {}
    # 馬連
    try:
        html = fetch_odds_single_type(date, track_cd, sponsor_cd, race_nb, "6")
        result["quinella"] = parse_quinella(html)
    except Exception as e:
        print(f"[odds_all] quinella fail: {e}", flush=True)
    _sleep()
    # ワイド
    try:
        html = fetch_odds_single_type(date, track_cd, sponsor_cd, race_nb, "7")
        result["wide"] = parse_wide(html)
    except Exception as e:
        print(f"[odds_all] wide fail: {e}", flush=True)
    _sleep()
    return result


def parse_exacta(html):
    """馬単 (bt5) パース。
    2テーブル、各テーブル row0 が2着馬番号ヘッダ。
    row1以降: 1着馬=行index、各ペア<th>1着馬番</th><td>オッズ</td>
    2着馬番 = row0 の列ヘッダ番号 (ペアindex順)"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tbl in soup.select("table.tb73"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        # row0 の列ヘッダ = 2着馬番号
        header_cells = rows[0].find_all(["th", "td"])
        col_nums = []
        for c in header_cells:
            try:
                col_nums.append(int(c.get_text(strip=True)))
            except ValueError:
                col_nums.append(None)
        for row_idx, row in enumerate(rows[1:], start=1):
            cells = row.find_all(["td", "th"])
            a = row_idx  # 1着馬
            pair_idx = 0
            for i in range(0, len(cells) - 1, 2):
                if pair_idx >= len(col_nums):
                    break
                b = col_nums[pair_idx]
                pair_idx += 1
                if b is None or b == a:
                    continue
                odds = _parse_float(cells[i+1].get_text(strip=True))
                if odds is None:
                    continue
                key = f"{a}-{b}"
                out[key] = {"odds": odds}
    return out


def parse_trio(html):
    """3連複 (bt9) パース。
    複数テーブル、各テーブル row0 が2頭ペア (1-2, 1-3, ...)。
    row1以降: <th>3頭目</th><td>オッズ</td>の繰り返し。"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tbl in soup.select("table.tb73"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        # row0 = 2頭ペアヘッダ
        header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            for i in range(0, len(cells) - 1, 2):
                pair_idx = i // 2
                if pair_idx >= len(header):
                    break
                try:
                    c = int(cells[i].get_text(strip=True))
                except ValueError:
                    continue
                odds = _parse_float(cells[i+1].get_text(strip=True))
                if odds is None:
                    continue
                pair = header[pair_idx]  # "1-2"
                parts = pair.split("-")
                if len(parts) != 2:
                    continue
                try:
                    nums = [int(parts[0]), int(parts[1]), c]
                except ValueError:
                    continue
                if len(set(nums)) != 3:
                    continue
                key = "-".join(sorted([str(x) for x in nums], key=lambda z: int(z)))
                out[key] = {"odds": odds}
    return out


def parse_trifecta(html):
    """3連単 (bt8) パース。
    複数テーブル、各row1以降: <td>1 → 2 → 3</td><td>オッズ</td>"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tbl in soup.select("table.tb73"):
        for row in tbl.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            combo_txt = cells[0].get_text(strip=True)
            if "→" not in combo_txt:
                continue
            parts = [p.strip() for p in combo_txt.replace("→", "-").split("-")]
            if len(parts) != 3:
                continue
            try:
                nums = [int(p) for p in parts]
            except ValueError:
                continue
            odds = _parse_float(cells[1].get_text(strip=True))
            if odds is None:
                continue
            key = "-".join(str(x) for x in nums)
            out[key] = {"odds": odds}
    return out


def fetch_odds_all_full(date, track_cd, sponsor_cd, race_nb, num_runners):
    """全券種 (単勝以外) を一括取得。
    Returns: {"quinella": {...}, "wide": {...}, "exacta": {...}, "trio": {...}, "trifecta": {...}}
    """
    result = {}
    parsers = [
        ("6", "quinella", parse_quinella),
        ("7", "wide", parse_wide),
        ("5", "exacta", parse_exacta),
        ("9", "trio", parse_trio),
    ]
    for bt, name, parser in parsers:
        try:
            html = fetch_odds_single_type(date, track_cd, sponsor_cd, race_nb, bt)
            result[name] = parser(html)
            print(f"    [odds_all] {name}: {len(result[name])}", flush=True)
        except Exception as e:
            print(f"    [odds_all] {name} fail: {e}", flush=True)
            result[name] = {}
        _sleep()
    # 3連単のみ軸馬ループ
    try:
        result["trifecta"] = fetch_trifecta_all(date, track_cd, sponsor_cd, race_nb, num_runners)
        print(f"    [odds_all] trifecta: {len(result['trifecta'])}", flush=True)
    except Exception as e:
        print(f"    [odds_all] trifecta fail: {e}", flush=True)
        result["trifecta"] = {}
    return result


def fetch_trifecta_all(date, track_cd, sponsor_cd, race_nb, num_runners):
    """3連単を軸馬(1着)ごとにループして全通り取得。
    num_runners は出走頭数。"""
    out = {}
    for hn in range(1, int(num_runners) + 1):
        url = (f"{BASE}/keiba/Odds.do?sponsorCd={sponsor_cd}&opTrackCd={track_cd}"
               f"&raceDy={date}&raceNb={race_nb}&viewType=0&betType=8"
               f"&horseNb={hn}&jikuNb=1")
        try:
            with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                out.update(parse_trifecta(r.text))
        except Exception as e:
            print(f"    [trifecta] hn={hn} fail: {e}", flush=True)
        _sleep()
    return out


# ============================================================
# 結果ページ パーサ (RaceResult.do)
# ============================================================

def _parse_int(txt):
    if txt is None:
        return None
    t = str(txt).replace(",", "").strip()
    import re as _re
    m = _re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def parse_result(html, race_id, race_meta=None):
    """結果ページをパース。
    Returns: {
        "race_id": str,
        "race_name": str,
        "surface": str, "distance": int,
        "runners": [...],  # 着順付き
        "finish_order": [1着馬番, 2着馬番, 3着馬番],
        "payouts": {...},  # 券種ごとの払戻
    }
    """
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("title")
    race_name = t.get_text(strip=True) if t else ""

    # レース情報 (距離・馬場)
    surface = ""
    distance = 0
    # タイトルや周辺テキストから抽出
    body_text = soup.get_text(" ", strip=True)
    import re as _re
    m = _re.search(r"(芝|ダ|障)\s*(\d{3,4})m", body_text)
    if m:
        surface = {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(m.group(1), "")
        distance = int(m.group(2))

    runners = []
    finish_order = []
    table = soup.select_one("table.tb70.w100pr.al-center.stripe")
    if table is None:
        return None
    rows = table.find_all("tr")
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 15:
            continue
        finish = _parse_int(cells[0].get_text(strip=True))
        frame = _parse_int(cells[1].get_text(strip=True))
        num = _parse_int(cells[2].get_text(strip=True))
        if num is None:
            continue
        horse_name = cells[3].get_text(strip=True)
        affiliation = cells[4].get_text(strip=True)
        age_sex = cells[5].get_text(strip=True)
        weight = _parse_float(cells[6].get_text(strip=True))
        jockey = cells[7].get_text(strip=True)
        trainer = cells[8].get_text(strip=True)
        hw_txt = cells[9].get_text(strip=True)
        # "507(-2)" 形式
        hw = None
        hw_change = None
        mhw = _re.search(r"(\d+)\s*\(([+-]?\d+)\)", hw_txt)
        if mhw:
            hw = int(mhw.group(1))
            hw_change = int(mhw.group(2))
        else:
            mhw2 = _re.search(r"(\d+)", hw_txt)
            if mhw2:
                hw = int(mhw2.group(1))
        time_str = cells[10].get_text(strip=True)
        margin = cells[11].get_text(strip=True)
        agari = _parse_float(cells[12].get_text(strip=True))
        corner = cells[13].get_text(strip=True)
        popularity = _parse_int(cells[14].get_text(strip=True))

        runners.append({
            "finish": finish,
            "frame_number": frame,
            "horse_number": num,
            "horse_name": horse_name,
            "affiliation": affiliation,
            "age_sex": age_sex,
            "weight": weight,
            "jockey": jockey,
            "trainer": trainer,
            "horse_weight": hw,
            "horse_weight_change": hw_change,
            "time": time_str,
            "margin": margin,
            "agari_3f": agari,
            "corner": corner,
            "popularity": popularity,
        })
        if finish is not None and finish <= 3:
            finish_order.append((finish, num))
    finish_order.sort()
    order = [n for _, n in finish_order]

    # 払戻金 (minipay テーブル)
    payouts = {}
    for tbl in soup.select("table.minipay"):
        for row in tbl.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            # 単勝/複勝/枠連/馬連/馬単/ワイド/3連複/3連単 など
            vals = [c.get_text(strip=True) for c in cells]
            if label:
                payouts.setdefault(label, []).append(vals)

    return {
        "race_id": race_id,
        "race_name": race_name,
        "surface": surface,
        "distance": distance,
        "runners": runners,
        "finish_order": order,
        "payouts": payouts,
        "source": "oddspark_result",
        **(race_meta or {}),
    }


def fetch_result(date, track_cd, sponsor_cd, race_nb):
    """結果ページを取得してパース。"""
    url = f"{BASE}/keiba/RaceResult.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}"
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    rid = f"nar-{date}-{track_cd}-{race_nb}"
    return parse_result(html, rid)


# ============================================================
# 非同期版 全券種オッズ取得 (高速化)
# ============================================================

async def fetch_odds_all_full_async(client, date, track_cd, sponsor_cd, race_nb, num_runners, inner_sem=None):
    """httpx.AsyncClient を渡して全券種オッズを並列取得。
    レート制御のため inner_sem (セマフォ) を任意で受け取る。"""
    import asyncio

    async def _get(url):
        if inner_sem is not None:
            async with inner_sem:
                try:
                    r = await client.get(url, timeout=20, follow_redirects=True)
                    return r.text if r.status_code == 200 else None
                except Exception:
                    return None
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
            return r.text if r.status_code == 200 else None
        except Exception:
            return None

    async def _fetch_one(bt, parser):
        url = (f"{BASE}/keiba/Odds.do?sponsorCd={sponsor_cd}&opTrackCd={track_cd}"
               f"&raceDy={date}&raceNb={race_nb}&viewType=0&betType={bt}")
        html = await _get(url)
        return parser(html) if html else {}

    async def _fetch_trifecta(hn):
        url = (f"{BASE}/keiba/Odds.do?sponsorCd={sponsor_cd}&opTrackCd={track_cd}"
               f"&raceDy={date}&raceNb={race_nb}&viewType=0&betType=8"
               f"&horseNb={hn}&jikuNb=1")
        html = await _get(url)
        return parse_trifecta(html) if html else {}

    result = {}
    # 5券種を並列
    ticket_tasks = [
        ("quinella", _fetch_one("6", parse_quinella)),
        ("wide", _fetch_one("7", parse_wide)),
        ("exacta", _fetch_one("5", parse_exacta)),
        ("trio", _fetch_one("9", parse_trio)),
    ]
    gathered = await asyncio.gather(*[t for _, t in ticket_tasks], return_exceptions=True)
    for (name, _), m in zip(ticket_tasks, gathered):
        result[name] = m if isinstance(m, dict) else {}

    # 3連単は軸馬ごとに並列
    if num_runners and num_runners > 0:
        tf_tasks = [_fetch_trifecta(hn) for hn in range(1, int(num_runners) + 1)]
        tf_gathered = await asyncio.gather(*tf_tasks, return_exceptions=True)
        merged = {}
        for m in tf_gathered:
            if isinstance(m, dict):
                merged.update(m)
        result["trifecta"] = merged
    else:
        result["trifecta"] = {}
    return result
