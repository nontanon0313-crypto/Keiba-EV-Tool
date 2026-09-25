"""セッション(cookie)付き + 候補URL群で払戻・着順が取れるURLを確定。"""
import os
import re
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
}

date = "20230101"
track_cd = "43"
sponsor_cd = "43"
race_nb = 1

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    # セッション確立（RaceListへ）
    print("=== step1: RaceList.do でcookie取得 ===")
    r0 = c.get(f"https://www.oddspark.com/keiba/RaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}")
    print(f"  status={r0.status_code} cookies={dict(c.cookies)}")

    candidates = [
        ("RaceResult_normal", f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}"),
        ("RaceResult_no_ref", f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sponsor_cd}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}"),
        ("OneDayRaceList",   f"https://www.oddspark.com/keiba/OneDayRaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}"),
        ("KaisaiRaceList",   f"https://www.oddspark.com/keiba/KaisaiRaceList.do?raceDy={date}"),
        ("Top",              "https://www.oddspark.com/keiba/"),
    ]

    for name, url in candidates:
        print(f"\n=== {name} ===")
        print(f"  url: {url}")
        try:
            r = c.get(url)
            s = BeautifulSoup(r.text, "html.parser")
            title = s.find("title")
            tt = title.get_text(strip=True) if title else ""
            has_haraido = ("払戻" in r.text) or ("払い戻" in r.text)
            has_finish = bool(re.search(r'>\s*1着\s*<|着順', r.text))
            has_horse = "フークサプライズ" in r.text
            tables = s.find_all("table")
            tclasses = [t.get("class") for t in tables]
            print(f"  status={r.status_code} len={len(r.text)}")
            print(f"  title: {tt[:80]}")
            print(f"  払戻={has_haraido} 着順={has_finish} 馬名={has_horse} tables={len(tables)}")
            print(f"  classes: {tclasses[:10]}")
            # 行の一部テキストを見る
            body = s.find("body")
            if body:
                txt = body.get_text(" ", strip=True)
                # '払戻' 周辺
                idx = txt.find("払戻")
                if idx >= 0:
                    print(f"  '払戻' 周辺: {txt[max(0,idx-30):idx+200]}")
            if r.status_code == 200 and len(r.text) > 3000:
                fname = f"debug_html/probe_ps_{name}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"  saved: {fname}")
        except Exception as e:
            print(f"  ERROR: {e}")

print("\n=== 保存済み OneDayRaceList の中身確認 ===")
p = "debug_html/probe_result_OneDayRaceList_do.html"
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        html = f.read()
    s = BeautifulSoup(html, "html.parser")
    print(f"  len={len(html)}")
    print(f"  title: {s.find('title').get_text(strip=True) if s.find('title') else ''}")
    print(f"  tables: {len(s.find_all('table'))}")
    for i, tb in enumerate(s.find_all("table")):
        txt = tb.get_text(" ", strip=True)
        print(f"  [{i}] class={tb.get('class')} first200={txt[:200]}")
        if i > 5: break
    print(f"  馬名ヒット: フークサプライズ={'フークサプライズ' in html}")
    print(f"  払戻ヒット: {'払戻' in html}")
    # '払戻' 周辺
    body = s.find("body")
    if body:
        t = body.get_text(" ", strip=True)
        for kw in ["払戻", "単勝", "馬連", "3連単"]:
            idx = t.find(kw)
            if idx >= 0:
                print(f"  '{kw}' 周辺: {t[max(0,idx-20):idx+120]}")
